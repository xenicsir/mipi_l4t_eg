# Plan de développement — Framework de tests eg_dt_camera_config_set.sh

## Vue d'ensemble (mise à jour 2026-04-17)

3 phases hors-matériel + 1 phase matériel.

```
P0 : Cohérence (host)       → eg_config.yaml ↔ hardware.yaml ↔ .debs
P1 : Script matrix (x86)    → eg_dt_camera_config_set.sh × 4 états extlinux × ports × cams
P2 : dpkg postinst (x86)    → dpkg-deb -x + bash preinst/postinst
P3 : Real dpkg -i (arm64)   → docker --platform=linux/arm64 + qemu-aarch64 + dpkg -i
P4 : Hardware               → streaming caméra sur vrai Jetson (manuel)
```

**Principe directeur : tester les DTBOs existants, pour les caméras existantes, sur des boards existantes. Source de vérité = `eg_config.yaml` + `test/config/hardware.yaml`.**

**Lancement :**
```bash
bash test/run_all.sh           # P0 → P1+P2 → P3 (build Docker + run)
bash test/run_all.sh --no-build  # skip rebuild Docker images
# Itération rapide :
RUN_PHASE=2 bash test/integration/run_all.sh --no-build   # just P2
```

---

## Niveau 1 — Integration Docker ✅

**Objectif :** valider que `eg_dt_camera_config_set.sh` sélectionne les bons overlays et que
le DT résultant est correct (nœud caméra actif, IMX désactivé, bus-width correct).

**Environnement :** container Ubuntu 22.04 + `dtc` + `fdtoverlay`.

**Mocks :** `detect_jetson_board.sh`, `config-by-hardware.py`, `find`, `grep`, `sudo`.

**Fichiers :**
```
test/
  run_all.sh                        # entry point (délègue à integration/)
  Dockerfile                        # image de test
  mocks/                            # mocks partagés
  dts/auvidea/                      # DTBs réels Auvidea X230D
  integration/
    run_all.sh                      # entry point intégration
    run_inside_container.sh         # setup + lancement matrix.py
    matrix.py                       # matrice de test principale
    verify_dt.py                    # vérification structure DT après overlay
```

**Caméras testées :** Dione, MicroCube, MicroCube640, SmartIR640, Crius1280, iLumos, Microlynx

**Matrice de boards / versions L4T :**

| Board | Versions |
|---|---|
| Jetson Nano t210 (nvidia-p3449) | 32.7.1, 32.7.6 |
| Xavier AGX (nvidia-p2822) | 35.1, 35.3.1, 35.4.1, 35.6.0, 35.6.1 |
| Xavier NX (nvidia-p3509) | 35.1, 35.3.1, 35.4.1, 35.6.0, 35.6.1 |
| AGX Orin (nvidia-p3737) | 35.3.1, 35.4.1, 35.6.0, 35.6.1, 36.4, 36.4.3, 36.4.4 |
| Orin NX (nvidia-p3768) | 35.6.0, 35.6.1, 36.4, 36.4.3, 36.4.4 |
| Forecr DSBOARD-ORNXS | 36.4, 36.4.3, 36.4.4 |
| Auvidea X230D | 35.3.1, 35.4.1, 36.4, 36.4.3, 36.4.4 |

**Ce que verify_dt.py vérifie :**
- DTB parseable par `dtc`
- Nœud caméra actif dans le DT mergé
- Pas de nœud IMX219/IMX477 actif
- `bus-width` correct dans le NVCSI channel

---

## Niveau 2 — Hardware-in-the-loop

**Objectif :** valider le déploiement complet sur une vraie Jetson avec une vraie caméra.

**Ce qui est testé :**
- Installation du `.deb` sur la target
- Reboot et application des overlays
- Apparition de `/dev/video*`
- Streaming GStreamer fonctionnel

**Boards cibles :**
- Orin NX (p3767) 36.4.4 — NVIDIA DevKit
- AGX Orin (p3737) 35.4.1 — Auvidea X230D
- Orin NX (dsboard-ornxs) 36.x — Forecr

**État :** ❌ non commencé
