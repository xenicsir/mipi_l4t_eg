#!/usr/bin/env python3
"""Generate a bounded physical qualification schedule from declared support."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import yaml
from generate_deployment_matrix import DeploymentMatrixGenerator

ROOT = Path(__file__).resolve().parents[1]

def version_key(version):
    return tuple(int(n) for n in str(version).split('.'))

def camera_modes(matrix, platform, camera):
    family = camera['family']
    board = matrix.platforms_by_id[platform]
    if family in board.get('unsupported_cameras', []):
        return []
    blocked = set(board.get('unsupported_formats', []))
    blocked.update(matrix.camera_db.get('platform_restrictions', {}).get(platform, {}).get('unsupported_formats', []))
    return [mode['pixel_format'] for res in matrix.camera_db['cameras'].get(family, {}).get('resolutions', [])
            if res['res'] == camera['resolution'] for mode in res['modes'] if mode['pixel_format'] not in blocked]

def available_versions(matrix, platform):
    return sorted((v for v in matrix.camera_db['versions'] if matrix.platform_available(platform, v)), key=version_key)

def generate(matrix, inventory):
    boards = inventory['boards']
    cameras = {name: camera for name, camera in inventory['cameras'].items()
               if any(r['res'] == camera['resolution'] for r in matrix.camera_db['cameras'].get(camera['family'], {}).get('resolutions', []))}
    excluded = sorted(set(inventory['cameras']) - set(cameras))
    budget = inventory['budget']; warnings = []; visits = []; locations = {}; state = {}
    wave_resources = {}; covered = set(); flashes = 0; kernel_switches = 0; moves = 0; placements = 0
    unknown = [b for b, cfg in boards.items() if not cfg.get('current_version')]
    if excluded:
        warnings.append('Inventory cameras outside enabled release scope: ' + ', '.join(excluded))
    recipes = []
    for recipe in inventory['visits']:
        selected = {port: cid for port, cid in recipe['cameras'].items() if cid in cameras}
        if selected: recipes.append(dict(recipe, cameras=selected))
    base_versions = {}
    for name, cfg in boards.items():
        versions = available_versions(matrix, cfg['platform'])
        candidates = [v for v in versions if int(v.split('.')[0]) == cfg['base_major']]
        if not candidates:
            raise ValueError('No supported base BSP for ' + name)
        current = str(cfg['current_version']) if cfg.get('current_version') is not None else None
        base_versions[name] = current if current in candidates else candidates[-1]
        state[name] = (current, cfg['platform'])
        if current is None:
            warnings.append(name + ': current BSP unknown; initial flash budget is provisional')
    wave_times = {}
    for index, recipe in enumerate(sorted(recipes, key=lambda v: v['wave']), 1):
        name = recipe['board']; board = boards[name]; wave = recipe['wave']
        platform = recipe.get('platform', board['platform'])
        versions = available_versions(matrix, platform)
        version = base_versions[name] if recipe['track'] == 'base' else versions[-1]
        if version not in versions:
            raise ValueError('Unsupported BSP/platform in visit ' + str(index))
        prior_version, prior_platform = state[name]
        flash = prior_version != version
        kernel_switch = not flash and prior_platform != platform
        flashes += int(flash); kernel_switches += int(kernel_switch)
        state[name] = (version, platform)
        resources = wave_resources.setdefault(wave, {'boards': set(), 'cameras': set()})
        if name in resources['boards']:
            raise ValueError('Board scheduled twice in one wave: ' + name)
        resources['boards'].add(name)
        visit_cameras = []; visit_moves = 0
        for port, cid in recipe['cameras'].items():
            if not 0 <= int(port) < board['ports']:
                raise ValueError('Port outside physical board: ' + name)
            if cid in resources['cameras']:
                raise ValueError('Camera scheduled twice in one wave: ' + cid)
            resources['cameras'].add(cid)
            for group in inventory.get('exclusive_power_groups', []):
                if len(set(group) & resources['cameras']) > 1:
                    raise ValueError('Shared camera power conflict in wave ' + str(wave))
            camera = cameras[cid]; modes = camera_modes(matrix, platform, camera)
            status = matrix.get_status(platform, camera['family'], version)[0]
            if status in (None, 'not_supported') or not modes:
                raise ValueError('Unavailable camera/modes: ' + cid + ' on ' + platform)
            location = (name, int(port))
            if locations.get(cid) != location:
                placements += 1; visit_moves += 1
                moves += int(cid in locations)
                locations[cid] = location
            covered.update({('model', cid), ('port', name, int(port)),
                            ('driver-board', camera['family'], name), ('bsp-board', version, name)})
            visit_cameras.append(dict(id=cid, port=int(port), family=camera['family'],
                                      resolution=camera['resolution'], modes=modes,
                                      historical_status=status))
        estimate = (budget['full_camera_minutes'] * len(visit_cameras)
                    + budget['placement_minutes'] * visit_moves + budget['reboot_minutes']
                    + budget['flash_minutes'] * int(flash)
                    + budget['reboot_minutes'] * int(kernel_switch))
        wave_times[wave] = max(wave_times.get(wave, 0), budget['full_camera_minutes'] * len(visit_cameras))
        visits.append(dict(id='V%02d' % index, wave=wave, board=name, platform=platform,
                           l4t=version, jetpack=matrix.camera_db['versions'][version]['jetpack'],
                           flash_required=flash, kernel_switch_required=kernel_switch,
                           initial_version_unknown=prior_version is None, cameras=visit_cameras,
                           estimated_minutes=estimate,
                           tasks=['artifact identity', 'enumeration and controls', 'all released modes',
                                  'three capture tools', 'start-stop', 'concurrent streams',
                                  'restore and kernel-log review']))
    missing_models = sorted(set(cameras) - {x[1] for x in covered if x[0] == 'model'})
    missing_ports = [(name, port) for name, b in boards.items() for port in range(b['ports'])
                     if ('port', name, port) not in covered]
    if missing_models: warnings.append('Unscheduled camera models: ' + ', '.join(missing_models))
    if missing_ports: warnings.append('Unscheduled connectors: ' + repr(missing_ports))
    sampled = {(v['platform'], v['l4t']) for v in visits}
    unsampled = [(p, v) for p in matrix.platforms_by_id for v in available_versions(matrix, p)
                 if (p, v) not in sampled]
    missing_families = sorted(set(matrix.camera_db['cameras']) - {c['family'] for c in cameras.values()})
    if missing_families:
        warnings.append('Enabled families without a physical inventory sample: ' + ', '.join(missing_families))
    # Human setup/flash time is serialized, even when independent tests overlap.
    hands_on = (placements * budget['placement_minutes'] + flashes * budget['flash_minutes']
                + (len(visits) + kernel_switches) * budget['reboot_minutes'])
    bench_minutes = sum(v['estimated_minutes'] for v in visits) + len(boards) * budget['soak_minutes']
    # Conservative: serialize preparation, then parallelize only independent tests.
    # Two soak windows preserve the iLumos/MicroLynx power exclusion.
    cold_boot_minutes = len(boards) * 2 * budget['reboot_minutes']
    elapsed = hands_on + sum(wave_times.values()) + 2 * budget['soak_minutes'] + cold_boot_minutes
    days = elapsed / (budget['hours_per_day'] * 60)
    if days > budget['working_days']:
        warnings.append('Nominal wall-time estimate exceeds the campaign budget')
    return dict(schema=1, status='planned-not-executed', visits=visits, warnings=warnings,
                coverage=dict(inventory_models=len(inventory['cameras']), excluded_inventory_models=excluded, camera_models=len(cameras)-len(missing_models),
                              physical_ports=sum(b['ports'] for b in boards.values())-len(missing_ports),
                              missing_ports=missing_ports, missing_models=missing_models,
                              unsampled_platform_versions=unsampled),
                costs=dict(flashes=flashes, unknown_initial_versions=len(unknown),
                           kernel_switches=kernel_switches, camera_relocations=moves,
                           initial_placements=placements-moves, hands_on_minutes=hands_on,
                           aggregate_bench_minutes=bench_minutes,
                           cold_boot_minutes=cold_boot_minutes, nominal_elapsed_minutes=elapsed, nominal_days=round(days, 2),
                           reserve_minutes=budget['working_days']*budget['hours_per_day']*60-elapsed))

def render(plan):
    lines=['# Release qualification schedule', '',
           'Generated from declared support and the physical inventory. Planned coverage is not test evidence.', '',
           '| Visit / wave | Board | L4T / package profile | Cameras by port | Preparation |',
           '| --- | --- | --- | --- | --- |']
    for v in plan['visits']:
        prep='flash' if v['flash_required'] else 'kernel/package switch' if v['kernel_switch_required'] else 'keep BSP'
        if v['initial_version_unknown']: prep+=' (verify current BSP first)'
        lines.append('| %s / %s | %s | %s / %s | %s | %s |' % (v['id'],v['wave'],v['board'],v['l4t'],v['platform'],
                     '; '.join('%s: %s (%s)' % (c['port'],c['id'],', '.join(c['modes'])) for c in v['cameras']),prep))
    lines += ['', 'Only visits in the same wave may overlap. Power down/disconnect cameras outside their scheduled visit.',
              'iLumos and MicroLynx share a supply and cannot be active together.', '',
              '## Estimated effort', '', '```json',json.dumps(plan['costs'],indent=2),'```', '',
              'The estimate assumes prebuilt packages, prepared flash media and no fault investigation. Reserve the remaining time for retests.',
              '', '## Items to resolve', ''] + ['- '+w for w in plan['warnings']]
    lines += ['', '## Supported platform/BSP pairs not sampled on hardware', '',
              'These remain covered only to the extent established by the host tests and the reviewed BSP differences.', '']
    lines += ['- %s: %s' % pair for pair in plan['coverage']['unsampled_platform_versions']]
    return '\n'.join(lines)+'\n'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,default=ROOT/'test/hardware/release_inventory.yaml')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    matrix=DeploymentMatrixGenerator(ROOT/'tools/deployment_matrix_data.yaml')
    plan=generate(matrix,yaml.safe_load(args.inventory.read_text()))
    inputs=[ROOT/'eg_config.yaml',ROOT/'tools/deployment_matrix_data.yaml',args.inventory]
    plan['inputs']={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    plan['git_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    (args.output/'plan.md').write_text(render(plan))
    print(json.dumps(plan['costs'],indent=2))
    for warning in plan['warnings']:print('REVIEW:',warning)
    return 0
if __name__=='__main__':sys.exit(main())
