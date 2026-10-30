# Qualification de non-régression avant release

## Objectif et périmètre

Prévoir trois journées de banc, avec build et tests hôte lancés la veille si
possible. La campagne couvre tous les modèles disponibles, les familles de SoC,
les variantes de BSP représentatives, les formats livrés et les connecteurs des
six carriers. Elle ne prétend pas démontrer toutes les combinaisons : le rapport
conserve explicitement les couples non essayés et le risque résiduel accepté.

La liste des BSP est **exclusivement celle déclarée supportée dans le dépôt**.
Aucun portage futur n'entre dans ce plan. Les prochaines versions deviennent des
candidates seulement après leur déclaration dans la configuration de support.

## Entrées et génération

- `eg_config.yaml` : BSP, vendors/carriers, caméras, résolutions, modes activés et
  restrictions des plateformes.
- `tools/deployment_matrix_data.yaml` : plateformes, rattachement aux packages de
  carrier, statuts historiques et restrictions du noyau vendor. « Tested » dans
  cette matrice ne constitue pas une preuve pour la nouvelle release.
- `test/config/hardware.yaml` : fixtures et nombre de ports couverts hors cible.
- `test/hardware/release_inventory.yaml` : matériel physique, BSP actuellement
  installé, séquence de manipulations, budget et exclusion d'alimentation.

```sh
python3 tools/plan_release_validation.py \
  --inventory test/hardware/release_inventory.yaml --output /tmp/release-plan
```

Les sorties `plan.json` et `plan.md` contiennent les versions résolues, les
branchements, les reflashages estimés, les couples non échantillonnés et les
empreintes des entrées. Renseigner les `current_version: null` avant de réserver
les créneaux : l'estimation pessimiste compte un flash initial pour chaque BSP
inconnu. Vérifier aussi le vendor effectivement démarré sur Hadron.

La règle `base` conserve un BSP installé encore supporté dans sa famille ; sinon
elle prend le plus récent déclaré pour cette famille et ce carrier. La règle
`latest` choisit la version la plus récente supportée par cette plateforme. Une
version absente d'`eg_config.yaml` ne peut pas être sélectionnée. Les profils
Hadron sont limités aux versions explicitement déclarées dans leur rattachement.

L'inventaire comprend MicroCube, Crius1280, SmartIR640, les quatre Dione
320/640/1024/1280, iLumos et MicroLynx. **iLumos et MicroLynx ne peuvent jamais être
alimentées simultanément**, même sur des boards différentes. Le générateur
rejette ce conflit, une caméra employée sur deux bancs dans la même vague et un
numéro de port hors de la capacité déclarée.

Le plan est une heuristique adaptée à cet inventaire, pas une preuve d'optimalité.
À chaque évolution, régénérer et examiner les avertissements : une caméra ou un
port non planifié, un nouveau profil supporté ou un modèle activé absent de
l'inventaire demande une décision explicite.

## Organisation des bancs

Chaque vague peut être parallèle à l'intérieur de ses contraintes. Terminer les
essais d'un appareil avant de le déplacer ; couper les alimentations avant de
changer un câble CSI. Les appareils qui ne participent pas à la vague sont
éteints ou débranchés. Ne jamais débrancher une caméra encore utilisée par un test.

| Vague | Bancs et caméras | But principal |
| --- | --- | --- |
| 1 | Nano : MicroCube + Dione320 ; Xavier NX : SmartIR640 + Dione640 ; Forecr : Crius1280 + iLumos ; AGX X230D : Dione1280 ; Hadron : Dione1024 | Tous les modèles sauf MicroLynx ; VI2/VI5/VI6 ; petits et grands timings Dione ; première passe sur chaque carrier |
| 2 | Orin Nano : MicroCube + MicroLynx ; Hadron : Dione1024 sur l'autre port et profil noyau vendor | FIFO16 ; second connecteur Hadron ; vérifier les limites du package pristine |
| 3 | Orin Nano et Forecr : passer au BSP le plus récent déclaré pour chacun ; garder MicroCube/MicroLynx sur Orin, Crius1280/Dione320 sur Forecr | Limiter à un passage vers le BSP récent par board ; frontières de noyau et vendor |
| 4 | Orin : MicroCube + Dione1024 ; AGX : Dione1280 + Dione640 + SmartIR640 + Dione320 ; Xavier : MicroLynx | Quatre ports AGX ensemble, coexistence, plus Y14 sur T194 et Dione sur le nouveau noyau |
| 5 | Orin : MicroCube + iLumos | Buffer1024, ordre des octets et contrôle pendant vidéo sur le BSP récent |
| 6 | Hadron, noyau EG : iLumos + MicroCube | Contrôle GenCP et formats RAW dans le framework CTI recompilé ; deux ports et deux familles |

Cette séquence limite les changements d'alimentation à iLumos → MicroLynx →
iLumos. Les variantes CTI sur une même version demandent une sélection correcte
du noyau/package et un reboot ; elles ne doivent pas être assimilées à une
compatibilité ABI automatique entre leurs modules.

Les ports sans changement de caméra sont testés en place. Pour l'AGX, l'essai à
quatre caméras évite de promener une caméra sur les quatre ports et couvre en
plus les ressources partagées. Les variants Dione ne sont pas interchangeables
pour une première qualification : leurs dimensions et timings diffèrent.

## Budget

Les coûts sont éditables dans l'inventaire. Ordres de grandeur provisionnés :
30 min par caméra pour une passe complète (formats, contrôles, cycles et reprise
manuelle éventuelle), 8 min par placement/déplacement, 5 min par reboot et 75 min
par flash, vérification du boot comprise. Ces durées sont des budgets de travail,
pas des mesures garanties. Les phases de flash sont comptées de façon conservatrice.

Le plan généré explicite le nombre de BSP initiaux inconnus : ce ne sont pas des
reflashages forcément nécessaires. Avec les BSP de base déjà installés, seules
les deux boards dédiées à la couverture du BSP récent nécessitent normalement
un reflashage. Les autres restent fixes.

- Veille : gel du candidat, build propre et tests hôte, préparation des images et
  moyens de récupération. Les corrections de portage sont un travail préalable.
- Jour 1 : inventaire réel, installation/upgrade, vagues 1 et 2. Lancer les soaks
  des bancs fixes avant de déplacer leurs caméras.
- Jour 2 : reflashages groupés, vagues 3 et 4. Soak du nouveau noyau et du banc
  AGX à quatre caméras ; vérifier que les caméras nécessaires restent disponibles.
- Jour 3 : vagues 5 et 6, cold boots restants, répétition des anomalies et bilan.

Provisionner une heure d'endurance par banc ; les bancs indépendants peuvent la
faire en parallèle. Ordonner ces fenêtres avant les déplacements et respecter
l'alimentation partagée. Les chiffres du générateur sont un budget nominal,
pas un ordonnanceur de toutes les interventions humaines : ajouter les temps
réels de flash, changement de firmware et récupération s'ils dépassent l'hypothèse.
Si une régression nécessite une investigation, interrompre la campagne concernée
et établir un nouveau délai ; ne pas diminuer les critères pour tenir trois jours.

## Étape A : candidat et couverture hors cible

1. Figer commit/tag, versions des firmwares, images BSP, archives carrier et
   paramètres de flash. Garder les SHA256 des packages, modules, DTBO et outils.
   Vérifier que les probes permissifs et autres réglages de diagnostic ne sont
   pas activés par défaut, et que les géométries correspondent aux spécifications
   caméra indépendantes des tables du pilote.
2. Rebuild depuis les sources prévues et terminer les contrôles décrits dans
   [l'audit hors cible](HOST_TEST_COVERAGE.md). Tous les packages annoncés sont
   concernés, même pour les versions non installées sur un banc physique.
3. Vérifier la cohérence publique et le candidat :

```sh
python3 tools/generate_deployment_matrix.py --check
python3 test/config/test_matrix.py --check
python3 test/config/check_release_scope.py --output /tmp/release-scope.json
bash test/run_all.sh --release --no-build
```

Pour une version de paquet de release sans suffixe Git, fournir la version Debian
exacte via `EG_RELEASE_PACKAGE_VERSION`. Une version de package ne prouve pas à
elle seule son contenu : archiver les empreintes des artefacts réellement testés.
Utiliser un arbre propre et un répertoire de livraison isolé du build précédent.

La phase ARM64 doit réellement s'exécuter. Classer chaque skip, XFAIL et XPASS ;
une absence de fixture de carrier n'est pas couverte par un test sur DTB NVIDIA.
Une dérogation formelle et temporaire doit indiquer responsable, motif, expiration
et essai matériel compensatoire ; le contrôle de scope accepte ce fichier via
`EG_RELEASE_WAIVERS`. Les paquets absents/périmés et sources suivies modifiées ne
sont pas dérogeables. Une dérogation ne transforme jamais un test absent en succès.

## Étape B : qualification sur chaque banc/BSP

### Installation et boot

- Enregistrer `/etc/nv_tegra_release`, `uname -r`, identité SoM/carrier, référence
  des caméras/câbles, firmware, configuration des ports et identifiant de boot.
- Une installation neuve par famille de système et par carrier particulier ;
  tester l'upgrade depuis la dernière release livrée sur les autres sessions.
  Réinstaller le même paquet vérifie seulement l'idempotence, pas l'upgrade.
- Après reboot, comparer les modules **chargés** aux artefacts attendus
  (srcversion/build-id) et les fichiers installés à leurs SHA256. Une capture
  réussie avec un ancien module n'est pas une validation du candidat.
- Vérifier le DT actif et les quatre chaînes sensor → CSI → VI → `/dev/video*`,
  avec le nombre de ports/caméras attendu. Une caméra attendue absente est un échec,
  même si le script sait ignorer les ports volontairement vides.
- Trois cold boots sur chaque banc de base : extinction board et caméra, délai
  hors tension, puis mise en marche. Ajouter un boot de la board avec caméra
  déjà alimentée et l'inverse. Un simple `reboot` ne couvre pas le démarrage à froid.

### Fonctionnement et formats

```sh
sudo python3 run_camera_regression.py --output /tmp/rc-functional \
  --recoveries 0 --xeneth-minimal /path/to/egXenethMinimal
```

Conserver les temporisations par défaut : 2 s entre commandes, 5 s après reboot
caméra/probe, 3 s avant capture. L'absence de client Xeneth est un échec pour les
caméras concernées ; `--skip-xeneth` sert uniquement aux comparaisons avec les
anciennes releases, pas au candidat.

- `--list-formats-ext` : formats/tailles sans doublons ; `--get-fmt-video` : format,
  dimensions, stride et taille réellement négociés.
- Vérifier tous les modes **livrés et applicables au BSP/package**. Un mode absent
  des commandes générées mais attendu par le plan demande une investigation ou
  une préparation de la caméra ; il ne peut pas être déclaré testé silencieusement.
- EngineCore : Y16, RGB et YUYV là où disponibles ; le runner évite désormais
  RAW16 sur un VI qui ne l'annonce pas. Sauvegarde/reboot au changement de format,
  puis restauration du format initial. Éviter les écritures EEPROM inutiles.
- Dione et MicroLynx : préparer les modes caméra nécessaires avant la passe si le
  pilote ne les commute pas. Respecter la procédure du firmware installé ; les
  commandes V4L2 ne prouvent pas que la caméra a changé de format sur le fil.
- iLumos : modes activés dans la configuration de livraison. Les essais d'un mode
  désactivé sont consignés à part et ne deviennent pas une promesse de support.
- Contrôles de registres avant/après vidéo avec `dioneCtrl.py` et `egCamCtrl.py` ;
  client minimal SDK pour iLumos/MicroLynx. Tester séparément les deux protocoles
  eSW iLumos, avec version/checksum identifiés et temps de démarrage après flash.
- Trois outils : capture V4L2, `rt_frame_monitor.py --display`, pipeline GStreamer
  généré sur l'image complète. L'absence de pipeline Y14 est N/A explicite.
- RGB : AR24/AB24 selon BSP ; leur coexistence historique ne signifie pas doublon.
  Vérifier visuellement orientation, couleurs/LUT et lignes/colonnes.
- Y14 : vérifier l'alignement annoncé par le SoC. Ne pas appliquer au Xavier le
  critère `max < 16384` d'un Orin configuré pour un alignement à droite.

### Endurance et coexistence

Copier les deux scripts `run_camera_regression.py` et `run_camera_endurance.py`
ensemble ; ils utilisent la bibliothèque standard Python et les outils de cible.

```sh
sudo python3 run_camera_endurance.py --output /tmp/rc-endurance \
  --plan /path/to/plan.json --visit V01 --cycles 20 --seconds 3600
```

Le script d'endurance est un contrôle strict : des captures peuvent réussir alors
que son bilan échoue sur des messages du noyau. Garder ces traces, comparer à la
référence et analyser la phase concernée avant d'autoriser une exception. Ne pas
masquer globalement `corr_err`. Le script conserve comme observations les seuls
statuts `UNKNOWN` (0), flags/error-data nuls, à moins de 0,5 s d'un arrêt qu'il a
mesuré. Le header NVIDIA les définit comme requêtes non exécutées/en cours ;
leurs autres champs ne sont pas interprétables. Le même message en plein flux,
un statut d'erreur effectif, un timeout ou des trames manquantes restent des échecs.
Pour isoler une anomalie, `--cycles 0` omet les cycles alternés et `--only`
sélectionne une caméra ; `--skip-nvmm` isole les captures V4L2.

Le second script vérifie les caméras attendues et le BSP, enchaîne des captures
courtes, puis lance les flux sélectionnés simultanément. Il détecte sorties
prématurées, absence de progression pendant 15 s, processus non arrêtables et
nouvelles erreurs noyau. Il conserve les formats déjà réglés. Une valeur
`--min-fps` doit venir de la spécification ou d'une référence mesurée, pas du
framerate parfois approximatif du DT. Ne pas interpréter le débit d'affichage
comme la cadence physique du capteur.

Après les flux V4L2, le runner tente automatiquement un contrôle fini multi-source
NVMM si au moins deux caméras sélectionnées disposent des commandes matérielles
générées. Chaque branche du même processus GStreamer est vérifiée à la source et
à la sortie : nombre de buffers, corruption, cadence mesurée. Les références
EngineCore proviennent de `rf 0x210`, avec les pauses de contrôle de 5 secondes.
Les formats courants sont conservés ; aucune bascule de format n'est faite par
le runner d'endurance.

Ajouter `--require-nvmm` aux visites où le plugin doit être présent. Son absence,
un format non pris en charge ou une seule caméra sont sinon consignés « non
applicable », jamais comme une validation NVMM. `--nvmm-frames` règle le nombre
par branche (180 par défaut), `--nvmm-timeout` son délai (30 s par défaut,
adapté si une référence de cadence lente est connue). Ce contrôle fini n'est pas
une endurance NVMM d'une heure. Il est sans affichage ; la validation graphique
reste celle du runner fonctionnel. La charge CPU mesurée couvre l'ensemble du
processus GStreamer, pas chaque branche séparément.

Collecter aussi températures, throttling, mémoire et cadence avec `tegrastats`
lors des soaks. Pour GenCP, répéter les lectures pendant le flux avec deux clients
et vérifier chaque réponse attendue, puis une écriture réversible/relecture d'un
registre documenté. L'endurance de flux seule ne remplace pas ce test concurrent
I2C. La version courante du nouvel outil ne réalise pas cette écriture.

Un cold boot, un upgrade, le débranchement physique et le changement de firmware
restent des étapes supervisées. Aucune décharge à chaud de `nvhost_isp5` ou du
framework caméra ne doit servir de récupération automatique.

### Intégrité réelle des images

Des trames reçues et des logs propres ne prouvent pas leur intégrité : certains
masques NVCSI réduisent la remontée d'erreurs. Capturer une mire déterministe
quand disponible et l'analyser avec `tools/pattern_integrity.py`, en conservant
les paramètres du générateur, le format et les fichiers bruts. Les deux bits bas
d'une mire qui ne les exerce pas restent non couverts. Un SHA256 de scène réelle
n'est pas une valeur de référence d'intégrité. Garder un échantillon par mode et
les données de chaque anomalie ; limiter la conservation du reste des soaks.

## Règles de décision et risque résiduel

| Dimension non exhaustive | Réduction hors cible | Ce qui reste à prouver matériellement |
| --- | --- | --- |
| Versions mineures non flashées | Builds pour chaque BSP, DTBO appliqués sur leurs DTB, contenu/install des packages, diff des fichiers modifiés | Boot, ABI chargée et runtime des versions aux frontières ou dont le framework/I2C change |
| Même caméra sur tous les ports | Graphe DT, lanes, index et endpoints de chaque overlay | Chaque connecteur au moins une fois ; coexistence sur le nombre de ports annoncé |
| Quatre tailles Dione sur chaque board | Calcul réel du bridge testé sur plusieurs géométries ; drivers partagés | Chaque modèle une fois, petites/grandes géométries, maxima de débit et alignement par SoC |
| EngineCore partout | Contrôle des variantes 1/2 lanes et tables de modes | Les trois modèles, 1/2 lanes, trois formats applicables et plus gros débit |
| GenCP sur chaque carrier/BSP | Vrai C, CRC, ACK, ID, erreurs, tailles, contextes et ABI historiques | FIFO16, buffer1024, protocole basique, contrôle simultané à la vidéo et démarrage réel |
| Profils CTI | Packages séparés et restrictions explicitement déclarées | Chaque noyau réellement utilisé ; CTI n'hérite pas d'une validation devkit NVIDIA |

L'équivalence de deux BSP doit être justifiée par le diff pertinent et les
résultats de leurs tests hôte, pas seulement par le même numéro de noyau.
Étendre la campagne pour un changement de framework VI/NVCSI, DT/mux/lanes,
timing/clock, transport I2C, bootloader, packaging ou dépendances de l'OS.
Pour une correction commune isolée, ajouter d'abord un test hôte discriminant,
puis retester les cellules qui exercent ce code et une cellule témoin.

Critères de sortie : aucune anomalie bloquante, aucun succès obtenu seulement
après recovery non expliquée, identité du candidat vérifiée, tous les modèles et
ports planifiés couverts, modes attendus tracés, exceptions nominatives et datées,
restauration des configurations et bilan des cellules non testées. Les statuts
« planned », « passed », « failed », « N/A » et « waived » restent distincts.

Une campagne répétée après correction doit utiliser les nouveaux artefacts et
conserver les échecs précédents. Ne mettre à jour les statuts historiques de la
matrice qu'à partir de preuves matérielles identifiées, sans généraliser un
résultat à une autre version ou à tous les ports.
