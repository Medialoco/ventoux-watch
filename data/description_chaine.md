# Version courte en place — à compléter

Les mots-dièse et la traduction anglaise de la description réellement en
ligne. Quinze mots-dièse et pas un de plus : au-delà, YouTube cesse de tous
les prendre en compte, les bons compris, et un seizième annulerait les quinze
autres. Les trois premiers sont les seuls à s'afficher au-dessus du titre, ce
qui en fait une enseigne plutôt qu'un classement.

## Mots-dièse — à coller tout en bas

`#FreeTechnoRadio` est déjà en tête de votre description et compte pour un :
ne le remettez pas ici, une répétition se compte deux fois. Voici les quatorze
autres, qui portent le total à quinze pile.

#MontVentoux #SlowTV #RaspberryPi #RaspberryPi5 #ComputerVision #EdgeAI #YOLO #SelfHosted #OpenSource #Python #LiveCam #CreativeCommons #FreeMusic #Techno

## À coller — traduction anglaise de la version courte

Sans mot-dièse en tête, celui de la version française servant pour les deux.

The camera looks down on the Mont Serein pass, at 1,389 m on Mont Ventoux, in Provence. One frame a second goes to a Raspberry Pi 5. The Pi finds what moved, cuts that patch out of the picture, asks a small neural network what it is, and then decides whether the answer can be trusted.

THE MUSIC

Free music only, 24 hours a day, with the licence on screen for every track.
Most of it comes from Dogmazic, a French free-music library running since 2004. Some of it is written for this channel.

thepriben: https://play.dogmazic.net/artists.php?action=show&artist=7208
Mont Serein 002: https://play.dogmazic.net/albums.php?action=show&album=11242
Dogmazic: https://play.dogmazic.net/

THE MACHINE

A Raspberry Pi 5 in Los Angeles. Four cores. It reads the webcam, runs the detector,
keeps the archive, composes the picture you are looking at, mixes the music and pushes
the whole thing to YouTube, without interruption.

This channel is a camera and a curiosity. It is not a monitoring service and it raises no alarm of any kind.

---

# Description de la chaîne — version longue

Texte brut, prêt à coller. Pas de markdown dans les deux blocs ci-dessous :
YouTube n'en rend aucun, et des dièses ou des astérisques s'y afficheraient
tels quels. Les titres sont donc en capitales, comme ceux déjà en place.

---

## À coller — anglais

A computer watches a mountain road and tries to say what just went past.

The camera looks down on the Mont Serein pass, at 1,389 m on Mont Ventoux, in
Provence. One frame a second goes to a Raspberry Pi 5 sitting on a desk. The Pi
finds what moved, cuts that patch out of the picture, asks a small neural
network what it is, and then — this is the part that takes the work — decides
whether the answer is worth believing.

The aim is everything that moves. Cars, vans and walkers today. Aircraft
overhead, cross-checked against live flight data. Birds, eventually, which are
the hard ones: fast, small, and shaped like nothing a camera at this distance
can resolve. We are not there yet. When we do not know, the screen says so.

HOW IT DECIDES

Nothing on screen is a guess dressed up as a fact.

Sizes are measured, not inferred from pixels. The camera's position, bearing,
tilt and field of view were solved against landmarks in the terrain, to about a
hundredth of a radian. From that pose, any patch of the image can be projected
onto a public elevation model and read back in metres. So the watcher does not
ask "does this look like a lorry" — it asks how wide the thing is on the
ground. Above 5.5 m it is not a car, whatever the network says. Below two
metres it is not a bus.

When the measurement cannot be trusted, it is thrown away rather than used.
Where the camera grazes its own foreground, three metres of error in the
terrain model move a subject by half its own length; past that threshold the
size rules simply switch off and the watcher says less.

The same honesty applies to the sun. Its position comes from the date and the
latitude, which is why the overlay can tell you the slope falls into the
mountain's own shadow a good hour before sunset. That is arithmetic, not
weather forecasting.

WHAT IT GETS WRONG

Plenty, and the failures are logged, replayed and counted.

A favourite: a car filling the frame was read as a boat, confidently, at 0.77.
The network had never seen an object touching all four edges of a picture —
there is always scenery around things in the photographs it was trained on. We
had been cropping tight to the subject and jamming it against the edge. Give it
the breathing room it expects and the same car reads as a car at 0.95. Measured
over two days of archive, that one framing change took road crossings from 63%
named to 86%.

That is the whole method: find the mistake, find why, fix the cause, measure
again. Never patch the symptom.

THE MUSIC

Free music only, 24/7, with the licence on screen for every track. Nothing here
forbids commercial use or editing, because the stream cuts music into slices
and ducks it under a voice — both of which are edits, and taking a licence
seriously means not using the ones that say no.

Most of it comes from Dogmazic, a French free-music library running since 2004.
Some of it is written for this channel. And yes, some of it is the author's own
first album, which is a thing you can do when you run the radio.

thepriben: https://play.dogmazic.net/artists.php?action=show&artist=7208
Mont Serein 002: https://play.dogmazic.net/albums.php?action=show&album=11242
Dogmazic: https://play.dogmazic.net/

THE MACHINE

One Raspberry Pi 5. Four cores. It reads the webcam, runs the detector, keeps
the archive, composes the picture you are looking at, mixes the music, and
pushes the whole thing to YouTube, continuously. Nothing runs in a cloud. The
detector takes 334 ms per look, and that is the budget everything else is built
around.

It is a camera and a curiosity. It is not a monitoring service, it raises no
alarm of any kind, and nothing it says should be acted upon.

---

## À coller — français

Un ordinateur regarde une route de montagne et essaie de dire ce qui vient de
passer.

La caméra domine le col du Mont Serein, à 1 389 m sur le mont Ventoux, en
Provence. Une image par seconde arrive sur un Raspberry Pi 5 posé sur un
bureau. Le Pi trouve ce qui a bougé, découpe ce morceau d'image, demande à un
petit réseau de neurones ce que c'est, puis — et c'est là qu'est le travail —
décide si la réponse mérite d'être crue.

Le but, c'est tout ce qui bouge. Les voitures, les camionnettes et les
promeneurs aujourd'hui. Les avions au-dessus, recoupés avec les données de vol
en direct. Les oiseaux un jour, qui sont les plus difficiles : rapides, petits,
et d'une forme qu'aucune caméra ne résout à cette distance. Nous n'y sommes pas
encore. Quand nous ne savons pas, c'est écrit à l'écran.

COMMENT IL DÉCIDE

Rien à l'écran n'est une supposition déguisée en fait.

Les tailles sont mesurées, pas déduites des pixels. La position de la caméra,
son cap, son inclinaison et son champ ont été calés sur des repères du terrain,
au centième de radian près. De cette pose, n'importe quel point de l'image se
projette sur un modèle d'altitude public et se relit en mètres. Le veilleur ne
demande donc pas « est-ce que ça ressemble à un camion » : il demande quelle
largeur ça fait au sol. Au-dessus de 5,5 m ce n'est pas une voiture, quoi qu'en
dise le réseau. En dessous de deux mètres ce n'est pas un car.

Quand la mesure ne vaut rien, elle est jetée plutôt qu'utilisée. Là où la
caméra rase son propre avant-plan, trois mètres d'erreur dans le modèle
d'altitude déplacent un sujet de la moitié de sa longueur ; passé ce seuil, les
règles de taille s'éteignent et le veilleur en dit moins.

La même honnêteté vaut pour le soleil. Sa position vient de la date et de la
latitude, et c'est pourquoi le bandeau peut annoncer que le versant entre dans
l'ombre du Ventoux une bonne heure avant le coucher. C'est de l'arithmétique,
pas de la météorologie.

CE QU'IL RATE

Beaucoup, et les échecs sont journalisés, rejoués et comptés.

Un préféré : une voiture occupant toute l'image a été lue comme un bateau, avec
aplomb, à 0,77. Le réseau n'avait jamais vu d'objet touchant les quatre bords
d'une photographie — il y a toujours du décor autour des choses, dans celles
qui l'ont entraîné. Nous découpions au ras du sujet et nous le collions au
bord. Rendez-lui l'air qu'il attend, et la même voiture se lit « voiture » à
0,95. Mesuré sur deux jours d'archives, ce seul changement de cadrage a fait
passer les traversées de chaussée de 63 % à 86 % de lectures nommées.

C'est toute la méthode : trouver la faute, trouver pourquoi, réparer la cause,
remesurer. Jamais rapiécer le symptôme.

LA MUSIQUE

De la musique libre uniquement, 24 h sur 24, avec la licence à l'écran pour
chaque morceau. Rien ici n'interdit l'usage commercial ni la modification,
parce que le flux découpe la musique en tranches et la passe sous une voix —
deux modifications ; et prendre une licence au sérieux, c'est ne pas se servir
de celles qui disent non.

L'essentiel vient de Dogmazic, médiathèque de musique libre française qui
tourne depuis 2004. Une partie est écrite pour cette chaîne. Et oui, une partie
est le premier album de l'auteur, ce qu'on peut se permettre quand on tient la
radio.

thepriben : https://play.dogmazic.net/artists.php?action=show&artist=7208
Mont Serein 002 : https://play.dogmazic.net/albums.php?action=show&album=11242
Dogmazic : https://play.dogmazic.net/

LA MACHINE

Un Raspberry Pi 5. Quatre cœurs. Il lit la webcam, fait tourner le détecteur,
tient l'archive, compose l'image que vous regardez, mixe la musique et pousse
l'ensemble vers YouTube, sans interruption. Rien ne tourne dans un nuage. Le
détecteur prend 334 ms par regard, et c'est le budget autour duquel tout le
reste est construit.

C'est une caméra et une curiosité. Ce n'est pas un service de surveillance, il
ne déclenche aucune alerte d'aucune sorte, et rien de ce qu'il dit ne doit être
suivi d'effet.
