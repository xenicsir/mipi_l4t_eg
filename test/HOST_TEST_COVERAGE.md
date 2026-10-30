# Audit de la couverture hors cible

## Lecture des résultats

Les tests hors cible justifient la réduction du nombre de manipulations sur les
boards. Ils ne remplacent pas la vérification du binaire chargé, du boot ni du
signal CSI réel. Un calcul correct du bridge ne prouve pas que ses écritures sont
arrivées sur le composant. Un DTB cohérent ne prouve pas le câblage physique.

Le point d'entrée est `test/run_all.sh`. `test/PLAN.md` décrit l'historique de la
construction du framework ; ses anciennes listes de boards et compteurs ne sont
pas un inventaire de couverture actuel. La liste exécutée est générée depuis les
fichiers de configuration, et doit être archivée avec chaque candidat.

## Ce qui est réellement vérifié

| Ensemble | Assertions utiles | Limites et conséquence sur le plan HW |
| --- | --- | --- |
| P0 `test_matrix.py --check` | Cohérence des chemins DTB/DTBO/package des entrées générées | L'existence d'un fichier ne prouve ni sa fraîcheur ni l'identité du binaire chargé. Contrôle de scope séparé avant release |
| `test_tc358746_equivalence.py` | Exécution du vrai calcul C et comparaison avec le portage Python, vecteurs limites et overflow volontaire | Ne remplace pas une référence indépendante du protocole ni un signal physique. Garder petits/grands capteurs et familles de cadence |
| Tests C iLumos/Titan/MicroLynx | Transactions, format/probe, sélection, nettoyage et durée de vie des descripteurs ; ASan/UBSan | Fonctions extraites avec shims, pas un noyau complet ; les races, allocations, ABI compat et erreurs I2C réelles demandent encore essais ciblés |
| GenCP transport/échange | FIFO16/snapshot1024, CRC, ACK périmés, ID/rebouclage, tailles, erreurs, binaire et contextes | Le pair simulé connaît le protocole attendu. Garder la validation contre firmwares réels et le codec SDK indépendant |
| V4L2 enumeration | Fonctions réelles de plusieurs versions du framework, doublons/formats/tailles | Pas de DMA, timing, conversion réelle de pixels ou caps GStreamer de la cible |
| `egCamCtrl` et `dioneCtrl` | ABI/messages, endian, erreurs, longueurs, attente Dione et accès sans forçage | Mocks du périphérique ; le firmware, l'adresse et la concurrence sur le bus restent matériels |
| P1a/P1b | Script réel de configuration, DTBO réellement appliqués, quatre états extlinux, ports, erreurs CLI, graphe sensor/CSI/VI | `detect_jetson_board`, jetson-io, procfs et certaines commandes sont simulés. Les matrices ne couvrent pas toutes les paires de caméras simultanées |
| Contenu `.deb` | Modules/scripts/manifeste/DTBO présents, DTBO lisibles | Présence des modules n'implique pas ABI compatible, installation effective ou absence d'un ancien fichier résiduel |
| P2/P2b | preinst/postinst, install/upgrade, garde version/vendor, forçage L4T et nettoyage | Déploiement dans un conteneur, depmod simulé, pas d'initramfs réellement booté ni d'UEFI |
| P3/P3b | Exécution ARM64 dpkg et comportement apt/Recommends, plusieurs états de dépendances | QEMU et rootfs de test ne sont pas les différents Ubuntu/BSP de la matrice. XFAIL jetson-io et détection Forecr ne qualifient pas le vrai chemin d'installation |
| Tests des outils HW | Découverte, commandes, pacing, récupération bornée, lecture de registres/SDK, arrêt des enfants | Un test de l'orchestrateur ne constitue pas un résultat matériel de la campagne qu'il pilote |
| `rt_frame_monitor` backends/CPU | Refus CLI/JSON avant I/O, auto/classic/NVMM, absence de repli après erreur, routes Windows/Linux générique simulées, CPU portable et CSV | Les mocks ne qualifient ni Windows/Raspberry Pi réels ni les surfaces/accélérateurs NVIDIA ; compléter par le runner sur cible. Ces tests nécessitent les dépendances Python du moniteur (`numpy`, `opencv`) sur l'hôte |
| Runner d'endurance multi-source NVMM | Construction de branches indépendantes, périphériques conservés, comptage source/sortie, corruption, cadence, cas indisponible/obligatoire | Ne prouve pas la concurrence GPU réelle ; test cible en double Y16 normalisé et en combinaison Y16/YUYV |

## Garde-fous ajoutés

- Les vendors d'un test sont filtrés par carrier : les packages CTI ne sont plus
  crédités de tests sur un DTB NVIDIA générique.
- Les fixtures Forecr prennent leurs DTB/DTBO dans l'arbre de build Forecr.
- Un BSP ou une plateforme déclarés sans mapping de test font échouer P0 ; ils ne sont plus silencieusement ignorés.
- Une collection de packages vide fait échouer `check_packages.py`.
- `check_release_scope.py` énumère les variantes attendues depuis `eg_config.yaml`
  et exige un candidat de version/révision et d'architecture correctes. Il ne se
  contente pas du dernier mtime ou du paquet au SHA trié le plus haut.
- Le mode `--release` refuse de passer P3 sous silence quand ARM64/QEMU n'est pas
  disponible. Le bilan standard rappelle de lire les skips et échecs attendus.
- Des tests indépendants vérifient ces garde-fous, les restrictions Hadron et la
  validité physique du plan (alimentation, caméra unique, ports et versions).
- Dione : vrai codec basique testé sur attente initiale, busy borné sans renvoi
  de commande, mauvais status, réponses courtes, endian et fermeture des FD.
- Outils de cible : compatibilité syntaxique Python ancien, RAW16 non commandé
  sur un VI qui ne l'annonce pas, tests de contrôle/lifecycle des flux simultanés.

Ces changements ne signifient pas qu'une campagne P1–P3 complète a été exécutée
sur des packages nouvellement reconstruits. Il faut la refaire après gel du
candidat ; les preuves antérieures n'appartiennent pas automatiquement au RC.

## Manques prioritaires avant une qualification exhaustive

| Priorité | Complément | Effort indicatif | Gain / essai physique compensatoire |
| --- | --- | --- | --- |
| Bloquant ou dérogation explicite | Fixtures P1/P2/P3 Hadron avec vrai DTB CTI NGX024 et les deux profils noyau | 0,5–1 jour, sources vendor disponibles | Supprime les faux crédits des anciens tests CTI ; à défaut, installation + boot + deux ports sur le matériel pour chaque profil |
| Bloquant | Un même manifeste immuable de packages pour P0, contenu, P2/P3 et déploiement HW, avec SHA256 et commit interne | 0,5 jour | Les sélecteurs actuels mtime et ordre des commits diffèrent encore. `check_release_scope` détecte le RC absent, mais il ne réécrit pas tous les sélecteurs existants : isoler les artefacts du RC |
| Bloquant de périmètre | Réconcilier Xavier NX déclaré dans certains BSP legacy et exclusions `hardware.yaml`, ainsi que les caméras/profils non disponibles | 1–2 h de décision/documentation | Aucun tuple déclaré puis silencieusement ignoré. Ne pas ajouter une disponibilité pour faire taire une alerte |
| Élevée | Images ARM64 par génération Ubuntu/Python : système legacy, JP5, JP6, JP7 | 0,5–1 jour, cache images ensuite | Réduit les dépendances/interpréteurs non exercés par l'unique Ubuntu22.04 QEMU actuel ; garder une installation native par famille |
| Élevée | Contre-exemples DT : lane/index erroné, endpoint non réciproque, conflit de ports, sensor absent, mode décalé | 0,5 jour | Vérifie que le vérificateur lui-même échoue ; les assertions ne doivent pas être validées seulement par des arbres corrects |
| Élevée | Configurations multiports mixtes et permutation de l'ordre des arguments | 0,5 jour | Graphes et `num_csi_lanes`/caméras actives, indépendance d'un port non modifié ; garder les flux simultanés HW |
| Élevée | Contrats ABI GenCP 32/64 bits et client C++ avec erreurs ioctl simulées | 0,5 jour | Complète les tailles de structures actuelles et le C kernel ; ne remplace pas le chargement réel des modules |
| Élevée | CI des scripts de lecture/diagnostic : `get.sh`, `read_nvcsi`, mire/endianness sur fixtures indépendantes | 0,5–1 jour | Empêche une fausse lecture « propre » des registres ou images ; aucun script de diagnostic ne doit effacer les erreurs qu'il mesure |
| Moyenne | Scénarios d'upload Dione simulés : interruption, statut d'opération, blocs et fermeture | 0,5 jour | Sans flasher une vraie caméra pendant chaque non-régression |
| Moyenne | Installer/upgrade/downgrade/purge : comparer les fichiers possédés et préservés, initrd/extlinux/signatures, idempotence | 0,5–1 jour | Complète les tests actuels de nettoyage ; tester le chemin réellement supporté, ne pas imposer une politique destructive |
| Moyenne | Inventaire des skips/XFAIL/XPASS structuré avec motif stable et expiration | 0,5 jour | Une nouvelle absence de couverture ne doit pas garder un indicateur global vert |
| Moyenne | Défaillances du banc : commande absente, ENOSPC, processus bloqué, SSH perdu, annulation et restauration | 0,5 jour | Le résultat doit être failed/incomplete, pas passé grâce aux seules données antérieures |

Les efforts de ce tableau sont un backlog d'amélioration du framework, pas du
travail à refaire à chaque release et pas une promesse de les réaliser tous dans
la campagne de trois jours. Prioriser les lignes bloquantes et les composants
modifiés par le RC. Les autres réduisent progressivement les risques résiduels.

## Comment réduire le HW sans perdre le sens des résultats

1. Construire et contrôler tous les packages, même si seulement quelques BSP
   sont flashés. Aucun contrôle hôte ne doit substituer un paquet générique à un
   paquet de carrier.
2. Établir des classes d'équivalence avec le diff des sources réellement
   compilées : noyau, framework caméra, I2C, DT, boot et espace utilisateur. Un
   numéro L4T voisin ne suffit pas à conclure à l'équivalence.
3. Garder des représentants des limites : VI2/VI5/VI6, noyaux majeurs, BSP vendor,
   1/2 lanes, horloge continue/discontinue, petit/grand capteur et RAW/RGB/YUV.
4. Pour chaque saut de HW, conserver la justification et le test hôte qui réduit
   le risque. Pour ce que le host ne peut mesurer, garder un test matériel ou
   une restriction de support explicite.
5. L'état « prêt pour tests hôte » n'est ni « host passé » ni « release validée ».
   Un résultat historique, une recette prévue ou une dérogation ne compte pas
   comme un essai réalisé sur le candidat.
