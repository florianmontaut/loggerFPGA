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
│   ├── recorder.py                enregistrement : un fichier csv (colonne trame) + .json, ou npz
│   ├── frame_buffer.py            mémoire tampon des dernières trames
│   ├── spectrum.py                FFT : fenêtres, amplitudes calibrées, moyennage, pics, THD
│   └── measures.py                mesures entre deux curseurs (Δt, Δy, min, max, moyenne, efficace)
├── controller/
│   ├── udp_worker.py              AcquisitionWorker(QThread) : boucle de logger.m
│   ├── acquisition_controller.py  démarrage / arrêt / relance du worker
│   ├── config_controller.py       ParameterTree <-> LoggerConfig (voie de seuil, grandeurs dérivées)
│   ├── channel_tree_controller.py arborescence des voies (visibilité, valeur sous le curseur)
│   ├── graph_controller.py        graphique temps réel (analogique + logique, seuil, curseur)
│   ├── fft_controller.py          spectre temps réel et réglages FFT
│   ├── buffer_controller.py       onglet Trames : mémoire tampon, relecture, sauvegarde, confirmations
│   ├── cursor_controller.py       curseurs de mesure (t1/t2, y1/y2) et mesures associées
│   ├── detach_controller.py       graphiques déportables dans leur propre fenêtre (écran déporté)
│   └── main_controller.py         câblage des contrôleurs et de la vue
├── view/main_window.py            fenêtre : barre d'outils, arbre, paramètres, graphiques, barre d'état
├── view/detached_window.py        fenêtre d'un graphique déporté
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
| `wr`, `pre`, `ch_name` | bouton *Enregistrer* (à tout moment, même pendant l'acquisition) + *Enregistrement › Dossier / Préfixe / Format* ; un seul fichier par enregistrement avec une colonne `trame`, au lieu d'un fichier par trame |
| `ch_gain` | *Description des voies › Gain (valeur à 1 pu)*, comme `ch_gain` : valeur = brut / 16384 × gain |
| `ylim` fixe | *Échelle auto* décochée : ±(multiple de 100 au-dessus du gain max) |
| `title(frame, Mo)` | titre du graphique (numéro de trame) ; compteurs de trames et d'erreurs dans la barre d'état |
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

### Mémoire tampon et navigation dans les trames

Comme dans PicoScope 7, les **dernières trames reçues restent en mémoire**, même sans
enregistrement : 64 par défaut, réglable dans *Mémoire tampon › Trames gardées*. La
mémoire nécessaire est affichée : de 160 à 230 ko par trame selon les voies, soit 10 à
15 Mo pour 64 trames (maximum réglable : 5 000 trames).

* **Onglet Trames**, à côté de l'onglet Voies : une ligne par trame, avec une vignette
  de la première voie, son numéro, son heure de capture, et ✓ si elle est enregistrée sur
  disque. Le compteur indique les trames en mémoire et celles qui ne sont pas encore
  enregistrées.
* **Relecture** : un clic sur une trame l'affiche. Graphiques, FFT, curseurs et
  valeurs de l'arborescence suivent. Le titre indique « mémoire tampon ». L'acquisition
  continue en arrière-plan et la mémoire tampon se remplit, mais l'affichage reste sur la
  trame choisie. Si elle sort de la mémoire tampon pendant la relecture, elle reste
  affichée et c'est signalé.
* **Navigation** : *Trame précédente* (Alt+←), *Trame suivante* (Alt+→), *Direct*
  (Alt+Fin). Ces raccourcis sont aussi actifs dans les fenêtres déportées. Depuis le
  direct, Alt+← affiche l'avant-dernière trame. Après la dernière, Alt+→ revient au
  direct.
* **Numérotation** : les numéros continuent d'une acquisition à l'autre, chaque trame a
  donc un numéro unique, dans la mémoire tampon comme dans les fichiers.
* **Sauvegarde** : *Fichier › Enregistrer la mémoire tampon...* (Ctrl+Maj+S, ou bouton
  de l'onglet) enregistre toutes les trames dans un seul fichier. Le menu contextuel de
  la liste enregistre seulement la sélection (Ctrl/Maj+clic).
* **Avant de quitter**, s'il reste des trames non enregistrées, l'application propose
  *Enregistrer*, *Ne pas enregistrer* ou *Annuler*. Même question avant une acquisition
  avec une autre disposition de voies (voies ou diviseur différents) : elle vide la
  mémoire tampon, car toutes ses trames doivent pouvoir être affichées par le même
  graphique et enregistrées dans le même fichier.

![mémoire tampon](docs/capture_memoire_tampon.png)

### Enregistrement des trames

**Format** : un seul fichier par enregistrement (auparavant, un fichier par trame).

```
enr_I_HV_V_PH1_INV2_Logic_div_20_20261103-143012.csv
trame,temps_s,I_HV (V),V_PH1_INV2 (V),K_HV,K_PRE,L2,...
12,0,57.31,-12.08,0,1,0,...
12,8e-07,57.42,-12.11,0,1,0,...
...
13,0,...
```

* `trame` : numéro de la trame (le même que dans le titre du graphique et dans l'onglet
  Trames) ; `temps_s` : temps depuis le début de la trame.
* À côté, `<même nom>.json` décrit l'enregistrement : configuration complète (voies,
  gains, diviseur, trigger…), fréquence d'échantillonnage et, pour chaque trame, son
  numéro et son heure de capture.
* Le CSV est écrit au fil de l'eau : il reste lisible même si l'application s'arrête
  brutalement.
* Le format npz contient les mêmes données en tableaux numpy (`trame`, `timestamp`,
  `time`, `analog` [trames × points × voies], `logic`, `raw`). Il est écrit à la fin de
  l'enregistrement.
* Un fichier existant n'est jamais écrasé (suffixe `_2`, `_3`…).

**Bouton Enregistrer**

* **Pendant l'acquisition**, il ouvre un fichier et y ajoute chaque trame dès la
  suivante. Un second clic ferme le fichier. La barre d'état affiche « ● REC ».
* **À l'arrêt**, il arme l'enregistrement pour le prochain *Démarrer* ou la prochaine
  *Trame unique*.
* **Dossier** : par défaut `Documents/LoggerFPGA`, modifiable dans *Enregistrement ›
  Dossier* ; *Acquisition › Ouvrir le dossier d'enregistrement* l'affiche.
* **En cas d'erreur** (dossier non accessible en écriture, disque plein…), un message
  s'affiche et le bouton se décoche. L'acquisition continue sans enregistrer.

Les trames enregistrées par ce bouton sont marquées ✓ dans la mémoire tampon : elles ne
sont pas proposées à nouveau avant de quitter.

### Curseurs de mesure

Groupe *Curseurs* de l'arbre des paramètres, sur le modèle des curseurs du GLviewer
(*Cursors menu* : Waveform, barres horizontales, verticales, H&V). *Type* propose
**Aucun**, **Verticaux**, **Horizontaux** ou **Verticaux + horizontaux**.

* **Curseurs verticaux t1 / t2** : deux lignes à faire glisser, présentes sur le
  panneau analogique comme sur le panneau logique (positions liées). Les champs *t1* et
  *t2* sont liés aux lignes dans les deux sens, et *Δt* et *1/Δt* sont affichés. Dans
  l'arborescence, la colonne *Valeur (t1)* donne la valeur de chaque voie en t1, et la
  colonne *Δ t2−t1* son écart y(t2) − y(t1). Pour une voie logique, cet écart vaut
  +1, 0 ou −1 : changement d'état entre les curseurs.
* **Curseurs horizontaux y1 / y2** : deux niveaux sur le panneau analogique, avec leur
  écart *Δy*.
* **Mesures** sur la *voie de mesure*, entre t1 et t2 : y(t1), y(t2), Δy, pente
  Δy/Δt, min, max, crête-crête, moyenne, valeur efficace, nombre d'échantillons. On
  choisit la voie dans le groupe ou en cliquant sur la voie dans l'arborescence.

Les valeurs sont celles de l'échantillon le plus proche de chaque curseur (curseur
« magnétique »). Un résumé (Δt, Δy, mesures) s'affiche en haut à gauche du graphique.
Les mesures suivent chaque nouvelle trame et restent figées avec *Figer*. Sans curseurs
verticaux, le double-clic place toujours le curseur simple.

![curseurs](docs/capture_cursors.png)

### Écran déporté

Chaque graphique peut être placé dans sa propre fenêtre, par exemple sur un deuxième
écran : **voies analogiques**, **voies logiques** et **spectre (FFT)**. Le graphique
temporel est découpé en deux widgets, avec les axes de gauche à largeur fixe pour garder
les échelles des temps alignées.

* Pour déporter : clic droit sur le graphique, puis *Déporter dans une fenêtre*. On peut
  aussi passer par le menu **Fenêtres** (une case par graphique, et *Tout réintégrer*).
* Pour réintégrer : fermer la fenêtre, ou clic droit puis *Réintégrer dans la fenêtre
  principale*. Le graphique revient à sa place d'origine.
* Les raccourcis F5 à F9 (Démarrer, Trame unique, Arrêter, Figer, FFT) restent actifs
  dans les fenêtres déportées.
* La fenêtre suit l'état du graphique. Si on décoche *FFT*, la fenêtre du spectre est
  masquée, puis réaffichée quand on la recoche. Une configuration sans voie logique (ou
  sans voie analogique) masque de même le panneau correspondant.
* Position et taille des fenêtres, ainsi que l'état déporté, sont conservés d'une session
  à l'autre (QSettings).
* Quand tous les graphiques sont déportés, la fenêtre principale affiche un message à
  leur place.

Repris du GLviewer (`view/detached_graph_window.py`, `GraphController.detach_panel`) : la
fenêtre dédiée, la réintégration à la fermeture, l'entrée du menu contextuel, le retour à
la place d'origine. Différence : le GLviewer déplace le `PlotItem` d'une scène pyqtgraph
à une autre, ce qui l'oblige à corriger les textes restés liés à l'ancienne scène
(`_release_scene`). Ici c'est le widget graphique entier qui change de fenêtre. Sa scène,
les connexions souris, les curseurs et les étiquettes le suivent donc sans traitement
particulier. Pour rendre un nouveau graphique déportable, il suffit d'un appel à
`DetachController.register(clé, titre, widget, [tracés])`.

![FFT déportée : fenêtre principale](docs/capture_main_fft_deportee.png)

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
| Fréquence max | limite haute de la zone affichée (0 : moitié de la fréquence d'échantillonnage) |
| Axe des fréquences | **Linéaire** ou **Logarithmique** (voir ci-dessous) |
| Voie analysée | voie des mesures ; un clic sur une voie de l'arborescence la sélectionne aussi |
| Pics repérés, harmoniques | nombre de pics marqués (20 dB au moins au-dessus du bruit), harmoniques prises dans le THD |

**Axe des fréquences linéaire ou logarithmique** : un seul réglage, accessible de trois
façons qui restent synchronisées :
- *Axe des fréquences* dans le groupe FFT ;
- clic droit sur le spectre, *Fréquences en échelle log* ;
- l'option *Log X* de pyqtgraph (clic droit, *Plot Options › Transforms*).

En échelle log, l'axe va de la résolution (première raie après le continu) jusqu'à la
fréquence max, avec des graduations aux décades écrites avec leur unité (10 Hz, 100 Hz,
1 kHz…) et des repères à 2 et 5. Le choix est conservé d'une session à l'autre. *Log Y*
de pyqtgraph est désactivé : marqueurs et mesures ne le suivraient pas, et l'échelle dB
joue ce rôle.

![FFT en échelle log](docs/capture_fft_log.png)

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

64 tests : protocole (octet par octet contre `logger.m`), FFT, curseurs, écran déporté, enregistrement, mémoire tampon, acquisition complète contre le
simulateur (trigger auto, seuil, pertes, arrêt, enregistrement), interface hors écran.

## 6. Points à valider sur la carte et pistes

* **À valider sur le FPGA** : le sens du *délai* (pré/post-trigger ?) pour décaler l'axe
  des temps ; le contenu des octets 2 à 5 des datagrammes de données (numéro de paquet ?)
  pour réordonner les paquets plutôt que de les prendre dans l'ordre d'arrivée.
* Persistance : superposer les N dernières trames (mode oscilloscope).
* Relire les enregistrements dans le GLviewer. Son import « .csv » attend le format de
  l'automate du chiller (colonnes X/Y alternées) : il faut un format d'export adapté ou un
  chargeur dédié, par exemple via l'assistant d'import texte.
* Une fois validée sur la carte, cette application peut remplacer `logger_FPGA/`
  (l'ancien code est laissé intact sur cette branche).
