# logger_app : logger FPGA temps réel (architecture GLviewer)

Application PyQt6 / pyqtgraph qui configure le logger du FPGA par UDP et affiche les trames
en temps réel. Elle reprend l'organisation du **GLviewer** (modèle / contrôleurs / vue,
arborescence des voies + arbre de paramètres + graphique) sans tout ce qui concerne les
fichiers (import Graphtec/CSV, filtres, analyses, undo/redo), et suit pas à pas le
script d'origine **`logger.m`**.

![capture](docs/capture_live.png)

*Capture prise pendant les tests, contre le simulateur : 3 voies analogiques + 16 voies
logiques, trigger automatique.*

---

## 1. État des lieux

### `logger.m` (référence fonctionnelle)

| Fonction | Détail |
|---|---|
| Sélection port/IP du PC | `port_msg` envoyé sur le port 9 |
| Configuration | trame de 32 octets : nb de canaux, voies (4 bits chacune), diviseur, délai, trigger, masque DJ, seuil |
| Trigger | 0 auto (le PC envoie `start_msg` à chaque trame), 1 disjonction, 2 > seuil, 4 < seuil |
| Seuil | `thres`, de -32768 à 32767, comparé à la **première voie** de `sig` |
| Lecture | `trig_msg` reçu → `read_msg` → 32 datagrammes de 1030 octets (16 384 mots) |
| Nombre de trames | `frame_nb` (`inf` = infini) |
| Voies logiques | indice 15, en dernière position ; 16 bits décodés et tracés en escalier |
| Enregistrement | un fichier par trame, gains `ch_gain` appliqués |

### `logger_FPGA/` (code Python existant) : problèmes relevés

* `UDPController.acquisition_FPGA` hérite de `QThread` sans `run()` : socket et timers
  vivent dans le thread de l'interface, et tout le dialogue UDP y tourne.
* Machine à états difficile à suivre et éloignée de `logger.m` : en trigger
  disjonction/seuil, `read_msg` (puis `start_msg` sur timeout) est envoyé avant tout
  déclenchement, et `start_msg` + `read_msg` sont renvoyés sans la pause `tempo`.
* `extractData` : la matrice des gains a toujours 15 lignes alors que les données en ont
  `n` (une par voie). Le produit échoue donc dès 2, 4 ou 8 voies. Les gains valent
  `[1]*15` et la division par 16384 n'est pas faite.
* Mode logique : le champ « nombre de canaux » reçoit 15, alors que `logger.m` envoie 1
  (avec `sig = [15]`).
* Non implémentés : seuil, limitation à N trames, enregistrement, décodage des voies
  logiques.
* Dépôt encombré : `__pycache__` versionnés, `UDPController_OLD.py`, chemins Windows codés
  en dur (`'.\logger_FPGA\logger.ui'`), deux `MainWindow` concurrentes.

## 2. Solutions étudiées

**Structure de l'application**

| Option | Avantages | Inconvénients |
|---|---|---|
| A. Reprendre `logger_FPGA/` | code déjà là | architecture ancienne (QTreeWidget + `CustomItems`), bugs ci-dessus, peu testable |
| B. Brancher l'acquisition dans le GLviewer complet | toutes les fonctions d'analyse disponibles | modèle pensé pour des fichiers statiques (`FileObject`, pipeline, undo), ~27 000 lignes à maintenir, rafraîchissement temps réel coûteux |
| **C. Nouvelle application, structure GLviewer simplifiée** (retenue) | même découpage MVC et même ergonomie, code court (~1 900 lignes), testable sans matériel | les outils d'analyse restent dans le GLviewer |

**Dialogue UDP**

| Option | Commentaire |
|---|---|
| `QUdpSocket` événementiel (existant) | non bloquant, mais il faut une machine à états complète (attente du trig, comptage des paquets, délais). C'est là que le code actuel diverge de `logger.m`. |
| **socket Python bloquante dans `QThread.run()`** (retenue) | traduction ligne à ligne de la boucle `logger.m`, lisible ; délais d'attente natifs ; l'interface ne bloque jamais (signaux Qt en file d'attente) ; arrêt par drapeau vérifié toutes les 0,2 s |
| processus séparé (`multiprocessing`) | utile seulement si le décodage ou l'enregistrement saturent le GIL à très haut débit ; à garder en réserve |

**Affichage temps réel** : le FPGA peut produire plus de trames que l'écran ne peut en
afficher (≈ 13 ms par trame avec div = 20). Le contrôleur du graphique ne garde que la
dernière trame et redessine au plus 30 fois/s. Les courbes sont créées une fois par
configuration puis mises à jour par `setData`, avec le sous-échantillonnage « peak » et
`clipToView` de pyqtgraph.

## 3. Architecture

```
logger_app/
├── main.py                        point d'entrée (python main.py [config.json])
├── model/
│   ├── config.py                  LoggerConfig : paramètres, validation, JSON (ancien format accepté)
│   ├── protocol.py                trames UDP (construction / décodage), Frame
│   ├── recorder.py                enregistrement d'une trame (csv : temps + une colonne par voie, npz)
│   └── spectrum.py                FFT : fenêtres, amplitudes calibrées, moyennage, pics, THD
├── controller/
│   ├── udp_worker.py              AcquisitionWorker(QThread) : boucle de logger.m
│   ├── acquisition_controller.py  démarrage / arrêt / relance du worker
│   ├── config_controller.py       ParameterTree <-> LoggerConfig (voie de seuil, grandeurs dérivées)
│   ├── channel_tree_controller.py arborescence des voies (visibilité, valeur sous le curseur)
│   ├── graph_controller.py        graphique temps réel (analogique + logique, seuil, curseur)
│   ├── fft_controller.py          spectre temps réel et réglages FFT
│   └── main_controller.py         câblage des contrôleurs et de la vue
├── view/main_window.py            fenêtre : barre d'outils, arbre, paramètres, graphique, barre d'état
├── ressources/pens.py             couleurs des voies (palette tab20 du GLviewer)
├── tools/fpga_simulator.py        simulateur du FPGA (UDP local)
└── tests/                         protocole, acquisition contre le simulateur, interface hors écran
```

Flux principal :

```
ConfigController ──config_changed──> ChannelTree / LiveGraph (aperçu)
[Démarrer]  ──> AcquisitionController.start(cfg) ──> AcquisitionWorker (thread)
AcquisitionWorker ──frame_ready(Frame)──> LiveGraphController.on_frame (dernière trame)
LiveGraphController (QTimer 30 Hz) ──cursor_values──> ChannelTreeController (colonne Valeur)
ChannelTreeController ──visibility_changed──> LiveGraphController.set_visible
```

## 4. Correspondance avec `logger.m`

| `logger.m` | logger_app |
|---|---|
| `chn`, `sig` | *Voies › Nombre de voies* et *Voie 1..8* ; la voie 15 (logique) n'est proposée qu'en dernière position |
| `div` | *Échantillonnage › Diviseur*, avec fréquence et durée de trame affichées |
| `del` | *Échantillonnage › Délai* (envoyé tel quel) |
| `trig` | *Trigger › Type* : Automatique / Disjonction / > seuil / < seuil |
| `trip` | *Trigger › Masque disjonction* (hexadécimal) |
| `thres` + voie en 1re position | *Trigger › Voie de seuil* : la voie choisie est **placée en tête de la liste** ; *Seuil (brut)* ou *Seuil (physique)* (converti avec le gain de la voie) ; ligne du seuil sur le graphique ; « (seuil) » dans l'arborescence |
| `frame_nb` | *Acquisition › Nombre de trames* (0 = infini) ; bouton *Trame unique* (F6) |
| `pl` | toujours actif ; *Figer* (F8) fige l'affichage sans arrêter l'acquisition |
| `wr`, `pre`, `ch_name` | bouton *Enregistrer* + *Enregistrement › Dossier / Préfixe / Format* ; noms `pre_voies_div_N_n.csv` |
| `ch_gain` | *Description des voies › Gain (valeur à 1 pu)*, comme `ch_gain` : valeur = brut / 16384 × gain |
| `ylim` fixe | *Échelle auto* décochée : ±(multiple de 100 au-dessus du gain max) |
| `title(frame, Mo)` | titre du graphique ; compteurs de trames et d'erreurs dans la barre d'état |
| `kbhit` / clic sur la figure | bouton *Arrêter* (F7) ; `stop_msg` envoyé à l'arrêt |
| `arp-ping` | non repris : l'absence de réponse est signalée dans la barre d'état (« sans réponse »), et `start_msg` est renvoyé toutes les 2 s en trigger automatique |

Les octets de la trame de configuration sont comparés à une transcription littérale du
calcul de `logger.m` (`tests/test_protocol.py`), de même que le découpage des voies
(`reshape` + `fliplr`).

## 5. Utilisation

```bash
pip install -r requirements.txt
python main.py                       # dernière configuration utilisée
python main.py ../logger_FPGA/ressources/parametres_scope.json
```

La configuration courante est enregistrée à la fermeture (dossier de configuration de
l'utilisateur) et peut être exportée ou rechargée en JSON (menu *Fichier*). L'ancien
format `parametres_scope.json` est accepté : ses gains par point sont convertis en
valeur à 1 pu.

Graphique : un double-clic place le curseur vertical. La colonne *Valeur* de
l'arborescence donne alors la valeur de chaque voie sous le curseur (sans curseur : le
dernier point de la trame). Les cases à cocher masquent ou affichent les courbes.

### FFT

Le bouton **FFT** (F9) affiche le spectre des voies analogiques sous le graphique
temporel. Il est calculé à chaque trame reçue, pour que le moyennage porte sur toutes les
trames et pas seulement sur celles qui sont dessinées. Réglages dans le groupe *FFT* de
l'arbre des paramètres :

| Réglage | Choix |
|---|---|
| Fenêtre | rectangulaire, hann, hamming, blackman, blackman-harris, flattop (amplitudes exactes même entre deux raies) |
| Retirer le continu | soustrait la moyenne de la trame avant la FFT |
| Échelle | amplitude crête, efficace, ou dB (réf. 1 unité crête) |
| Moyennage | aucun, moyenne des puissances des N dernières trames, maximum ; *Remise à zéro FFT* recommence |
| Fréquence max, fréquences en log | zone affichée |
| Voie analysée | voie des mesures ; un clic sur une voie de l'arborescence la sélectionne aussi |
| Pics repérés, harmoniques | nombre de pics marqués (20 dB au moins au-dessus du bruit), harmoniques prises dans le THD |

*Mesures* (lecture seule) : résolution et bande équivalente de bruit, nombre de trames
moyennées, fondamental (fréquence affinée par interpolation, amplitude), THD et liste des
pics. La valeur sous la souris est affichée au-dessus du spectre. *Figer* et les cases de
l'arborescence s'appliquent aussi au spectre.

Repris du GLviewer (`model/analysis/fft.py`) : le principe fenêtre + demi-spectre. Son
code dépend de son modèle (`AnalysisNode`, `DerivedSignalObject`) et ne calibre pas les
amplitudes, d'où le module autonome `model/spectrum.py`. Ce module pourrait en retour
servir au GLviewer.

La résolution vaut fréquence d'échantillonnage / points par voie : pour séparer des
composantes à 50 Hz, augmenter le diviseur (par exemple 500, soit 50 kHz, donne 12 Hz
avec 4 voies).

![FFT](docs/capture_fft.png)

### Sans carte : simulateur

```bash
python -m tools.fpga_simulator --ip 127.0.0.2 --cmd-port 9009
```

Dans l'application : IP du FPGA `127.0.0.2`, port de commande `9009`, IP locale
`127.0.0.1`. Le simulateur gère les quatre types de trigger. En seuil, la première voie
doit vraiment franchir le seuil pour déclencher. `--drop-rate 0.05` simule des pertes de
paquets.

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

43 tests : protocole (octet par octet contre `logger.m`), FFT, acquisition complète contre le
simulateur (trigger auto, seuil, pertes, arrêt, enregistrement), interface hors écran.

## 6. Points à valider sur la carte et pistes

* **À valider sur le FPGA** : le sens du *délai* (pré/post-trigger ?) pour décaler l'axe
  des temps ; le contenu des octets 2 à 5 des datagrammes de données (numéro de paquet ?)
  pour réordonner les paquets plutôt que de les prendre dans l'ordre d'arrivée.
* Persistance : superposer les N dernières trames (mode oscilloscope).
* Mesures au curseur (deux curseurs, Δt, Δy), comme dans le GLviewer.
* Relire les enregistrements dans le GLviewer. Son import « .csv » attend le format de
  l'automate du chiller (colonnes X/Y alternées) : il faut un format d'export adapté ou un
  chargeur dédié, par exemple via l'assistant d'import texte.
* Une fois validée sur la carte, cette application peut remplacer `logger_FPGA/`
  (l'ancien code est laissé intact sur cette branche).
