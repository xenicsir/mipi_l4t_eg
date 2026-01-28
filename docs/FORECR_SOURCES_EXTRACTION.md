# Extraction des sources Forecr pour L4T

Ce document décrit la procédure pour extraire les fichiers spécifiques Forecr depuis un dépôt kernel vendeur et les intégrer dans le framework de build.

## Vue d'ensemble

Le framework utilise une approche basée sur les patches :
1. Le BSP Nvidia original est téléchargé et extrait
2. Les sources spécifiques (Exosens, Forecr) sont copiées par-dessus
3. Des patches sont générés pour tracer les modifications

Pour ajouter le support d'un nouveau BSP Forecr, il faut extraire uniquement les fichiers qui diffèrent du BSP Nvidia original.

## Prérequis

1. **BSP Nvidia original extrait** dans `$L4T_VERSION/Linux_for_Tegra_forecr/source/public/`
2. **Dépôt kernel Forecr** contenant les répertoires `hardware/` et `kernel/`

## Méthode automatique (recommandée)

Utilisez le script `tools/extract_forecr_sources.sh` :

```bash
./tools/extract_forecr_sources.sh <L4T_VERSION> <CHEMIN_KERNEL_FORECR>
```

### Exemple pour L4T 35.6.0

```bash
# 1. Préparer le BSP Nvidia original
./l4t_prepare.sh 35.6.0 forecr

# 2. Extraire les sources Forecr
./tools/extract_forecr_sources.sh 35.6.0 ~/jetson/forecr_xavier_kernel

# 3. Vérifier et tester
./l4t_copy_sources.sh 35.6.0 forecr
./l4t_build.sh 35.6.0 forecr
```

### Exemple pour une nouvelle version L4T 36.x

```bash
# 1. Préparer le BSP Nvidia original
./l4t_prepare.sh 36.4.0 forecr

# 2. Extraire les sources Forecr (depuis un nouveau dépôt)
./tools/extract_forecr_sources.sh 36.4.0 ~/jetson/forecr_orin_kernel

# 3. Vérifier et tester
./l4t_copy_sources.sh 36.4.0 forecr
```

## Méthode manuelle

Si vous devez faire l'extraction manuellement :

### Étape 1 : Identifier les fichiers différents

```bash
# Définir les variables
FORECR_SRC="/chemin/vers/forecr_kernel"
NVIDIA_SRC="/chemin/vers/$L4T_VERSION/Linux_for_Tegra_forecr/source/public"

# Comparer hardware/
diff -rq "$FORECR_SRC/hardware" "$NVIDIA_SRC/hardware" 2>/dev/null

# Comparer kernel/
diff -rq "$FORECR_SRC/kernel" "$NVIDIA_SRC/kernel" 2>/dev/null
```

La sortie indique :
- `Only in $FORECR_SRC/...` → Fichiers **nouveaux** (à copier)
- `Files ... differ` → Fichiers **modifiés** (à copier)

### Étape 2 : Copier les fichiers

```bash
DEST="sources/$L4T_VERSION/Linux_for_Tegra_forecr/source/public"
mkdir -p "$DEST"

# Copier un fichier nouveau
mkdir -p "$DEST/hardware/nvidia/platform/..."
cp "$FORECR_SRC/hardware/nvidia/platform/.../fichier.dts" "$DEST/hardware/nvidia/platform/.../"

# Copier un fichier modifié
cp "$FORECR_SRC/kernel/kernel-5.10/drivers/.../fichier.c" "$DEST/kernel/kernel-5.10/drivers/.../"
```

## Structure des fichiers extraits

```
sources/$L4T_VERSION/Linux_for_Tegra_forecr/source/public/
├── hardware/
│   └── nvidia/
│       └── platform/
│           ├── t19x/           # Xavier
│           │   ├── galen/      # AGX Xavier
│           │   ├── galen-industrial/
│           │   └── jakku/      # Xavier NX
│           └── t23x/           # Orin
│               ├── common/
│               ├── concord/    # AGX Orin
│               └── p3768/      # Orin NX/Nano
└── kernel/
    └── kernel-5.10/
        ├── arch/arm64/configs/   # Defconfigs Forecr
        ├── Documentation/
        └── drivers/              # Drivers modifiés/nouveaux
```

## Types de fichiers couramment extraits

### Hardware (Device Trees)

| Type | Description |
|------|-------------|
| `tegra*-dsboard-*.dts` | Device trees pour cartes DSBoard |
| `tegra*-milboard-*.dts` | Device trees pour cartes Milboard |
| `tegra*-raiboard-*.dts` | Device trees pour cartes Raiboard |
| `tegra*-camera-*.dtsi` | Includes pour modules caméra |
| `Makefile` | Makefiles modifiés pour inclure les nouveaux DTS |

### Kernel

| Type | Description |
|------|-------------|
| `*_defconfig` | Configurations kernel pour cartes Forecr |
| `drivers/hwmon/` | Drivers capteurs (ex: ina238) |
| `drivers/iio/imu/` | Drivers IMU (ex: inv_mpu6050) |
| `drivers/net/ethernet/` | Drivers Ethernet (igb, lan743x) |
| `drivers/tty/serial/` | Drivers série (xr17v35x) |
| `drivers/usb/` | Drivers USB modifiés |

## Vérification

Après extraction, vérifiez que les fichiers sont corrects :

```bash
# Compter les fichiers extraits
find sources/$L4T_VERSION/Linux_for_Tegra_forecr -type f | wc -l

# Lister par catégorie
find sources/$L4T_VERSION/Linux_for_Tegra_forecr -name "*.dts" | wc -l  # Device trees
find sources/$L4T_VERSION/Linux_for_Tegra_forecr -name "*_defconfig" | wc -l  # Configs
```

## Intégration avec le workflow

Une fois les fichiers extraits :

1. **l4t_copy_sources.sh** copie ces fichiers vers le BSP
2. **l4t_patch_sources.sh** peut appliquer les patches générés
3. **l4t_build.sh** compile le kernel avec les modifications

## Dépannage

### Aucun fichier extrait

- Vérifiez que le BSP Nvidia est correctement extrait
- Vérifiez que le dépôt Forecr contient bien `hardware/` et/ou `kernel/`

### Fichiers manquants après build

- Vérifiez les Makefiles modifiés (ils doivent référencer les nouveaux .dts)
- Vérifiez les Kconfig pour les nouveaux drivers

### Erreurs de compilation

- Comparez les versions kernel entre Nvidia et Forecr
- Vérifiez les dépendances de drivers
