const CAMERA = { lat: 44.183501, lon: 5.2621281, bearing: 140 };
const STATIONS = [
  { name: "Avignon", lat: 43.9493, lon: 4.8055 },
  { name: "Carpentras", lat: 44.055, lon: 5.048 },
  { name: "Orange", lat: 44.136, lon: 4.809 },
  { name: "Apt", lat: 43.876, lon: 5.396 },
  { name: "Cavaillon", lat: 43.838, lon: 5.038 },
  { name: "Pertuis", lat: 43.695, lon: 5.503 },
];
const COPY = {
  en: {
    paris: "Paris time",
    weather: "Weather",
    passes: "Passes",
    namedLine: (named, habits) => `${named} named · ${habits} habits`,
    // The menu says it shorter than the headings do. The six links spelled out
    // in full took four hundred and seventy pixels of a row that has to hold
    // the title, the readings and the buttons as well, and a reader who is
    // already looking at the menu does not need "Live webcam" to guess which
    // one is the webcam.
    navLive: "Live",
    onYouTube: "Watch on YouTube",
    navHistory: "History",
    navFigures: "Dataviz",
    navRelief: "3D",
    navCamera: "Camera",
    navWeather: "Weather",
    navPipeline: "Pipeline",
    navStage: "Stage",
    navWatch: "Watch",
    navWiki: "Wiki",
    navNumbers: "On the stream",
    navMusic: "Dogmazic",
    watch: "The watch",
    watchLine: "OpenCV finds what moved. YOLO11s names the crop. One frame a second, on a Raspberry Pi 5 in Los Angeles. That reading is the work. The picture around it is the show.",
    pipelineLead: "A Raspberry Pi 5 in Los Angeles reads the Mont Serein webcam one frame a second and pushes the rebuilt picture to YouTube without a break.",
    numbers: "On the stream",
    numbersLead: "Eighteen ways the picture changes. Pixel, grey and wave share one draw every seven minutes, and two draws out of five leave the photograph alone. The set pieces take the stage one at a time. At night those set pieces come three times as often. The bear keeps his own pace.",
    effectColName: "Name",
    effectColWhat: "What happens",
    effectPixel: "Pixel",
    effectGrey: "Grey",
    effectWave: "Wave",
    effectFly: "Flyover",
    effectCatch: "Catch",
    effectConsole: "Console",
    effectBear: "Bear",
    effectCarpet: "Carpet",
    effectSub: "Submarine",
    effectPiste: "Piste",
    effectElephant: "Elephant",
    effectBuilding: "Building",
    effectSun: "Sun",
    effectLamp: "Lamp",
    effectMachine: "Machine",
    effectDogmazic: "Dogmazic",
    effectReplay: "Replay",
    effectMeet: "Meeting",
    musicTitle: "Dogmazic",
    musicLead: "Dogmazic is a free-music library. The artists keep the rights and choose a Creative Commons licence, so a stream can play the work in public as long as it names the author, the title, the licence and a place to find the file. Fourteen hours turn here, one hundred and fifty-three tracks, all from that library. Four of those hours are the album Mont Serein, written for this slope. The playlist is public.",
    rebuild: "Rebuilt",
    rebuildLead: "ffmpeg takes the webcam at one frame a second. OpenCV MOG2 finds what moved, on a frame scaled to 640 pixels. A compact blob held for three frames is cropped. YOLO11s, in ONNX, names only that crop. The named rectangle is drawn back onto the original picture, the overlays sit in the letterbox, and the whole frame is encoded toward YouTube. The mountain is never invented. It is read, then put back together.",
    watchMotion: "MOG2 finds the motion on the mountain.",
    watchClass: "A small network names the crop: car, walker, bike, truck.",
    watchOut: "The named frame is rebuilt and pushed live.",
    listen: "Listen on Dogmazic",
    radio: "Audio stream",
    radioOn: "Listening",
    chipFps: "1 frame / s",
    story: "The watch",
    heroLead: "A Raspberry Pi 5 in Los Angeles reads the Mont Serein webcam one frame a second, finds motion with OpenCV, names what moved with YOLO, and rebuilds the picture as a YouTube stream. The watch is the work. The stream is the show.",
    heroMachine: "Four cores on a desk, nine thousand kilometres from the pass. The Pi keeps the archive, mixes the music, draws the overlays and pushes the whole frame to YouTube in a continuous loop.",
    heroSee: "Vehicles and pedestrians are further along. Wildlife, birds, aircraft matched with OpenSky, and pets are where the work is going now. The model is trying to see everything that moves, and to name it correctly.",
    heroMusic: "Fourteen hours of free music play around the clock, all of it from Dogmazic. Four of those hours are the album Mont Serein, written for this slope. One hundred and fifty-three tracks sit in a public playlist you can open in a click.",
    stage: "On the stream",
    stageLead: "Pixel, grey and wave share one draw. A filmed flyover of the relief takes the window when the road is empty. The other rows are the set pieces.",
    stillConsole: "While a track plays, a console spans the width under the picture: the cover just finished, the one playing, and the next two. With the playing track sit the artist, the title, the licence and the domain of the file, the credit a stream can show where nothing is clickable. An equaliser follows the music. The release number of this build stays written there for the whole session.",
    stillPixel: "Every seven minutes the stream draws one treatment from five slots, and two of those slots are empty, so the photograph often stays as it is. When the draw is pixel, the frame shrinks to twenty-six columns and is enlarged again, nearest neighbour, for twenty seconds. It fades in and fades out over three and a half seconds at each end. Twenty-six columns leave the road and the crest recognisable. Pixel, grey and wave never run together. For four seconds after something named is on screen, they stay off, so the thing in the rectangle stays a thing you can look at.",
    stillGris: "The same draw, the same twenty seconds, the same fade. Colour mixes toward perceived luminance: a blue sky and a green slope of the same arithmetic mean do not have the same lightness to the eye, and the mix follows that lightness. At full strength the slope is grey, then the colour returns.",
    stillOndule: "The same draw. Twenty-eight horizontal bands slide sideways, by up to three percent of the width, as if the picture were under water. The Pi shifts whole rows. A remap of every pixel would be too heavy while it is encoding.",
    stillFly: "After five minutes with nothing named, and while no replay is up, a filmed flyover of the relief takes the camera window. By day it plays for two minutes, one JPEG per frame, a full out-and-back, so the loop joins on the webcam’s own viewpoint. At night it holds for a minute and a half on the middle frame, the farthest point, where the slope reads from the side. It stops the moment the watch sees something. Half an hour passes before the next one. The live picture stays in a small window. The dancers stay off this view. The Pi opens pictures it already has.",
    stillEclat: "A catch is a name the watch trusts while the thing is still in the picture: a car, a walker, a bike, a bus, a truck, a plane. The stream sits a few seconds behind the watch, so the celebration waits until that subject is on screen and the rectangle is drawn around it. GOOD CATCH! then crosses the mountain in green for a second and a half. A white flash dies in half a second. The name sits under the words, because the cheer alone does not say what was taken. At the same time the letterbox around the camera window lights in the colour of that kind of passage, for three and a half seconds, and the name is written large under the picture, over the cable and the top of the music console. Pixel, grey and wave hold off for four seconds, so the thing that passed stays a thing you can look at. The mountain itself stays the photograph.",
    stillRencontre: "Two puppets stand in the lower corners of the camera window when the music is pushing, drawn half transparent so the slope stays in front. About every seven minutes they leave those corners, meet in the middle of the window, hold for six seconds, and go home, four seconds each way. Between meetings they also step out into the black bands for a few seconds. During a flyover they are left off the relief.",
    stillTapis: "Every six minutes and thirty-seven seconds, when the music is pushing, a flying carpet crosses the whole frame in fourteen seconds, black bands included. It follows the crest, so it clears the summit. The figure on it is the same puppet as the two in the corners. If another number already holds the stage when this turn starts, the carpet waits for the next turn.",
    stillMarin: "Every eight minutes and forty-three seconds the yellow submarine from benoit-prieur.fr crosses the sky in twenty-two seconds. It follows the crest and pitches a tenth of its height, two and a half times during the crossing. It stays above the road, so it crosses on its turn whether the music is pushing or the slope is quiet. If the drawing is missing on the Pi, the crossing does not happen.",
    stillPiste: "Every thirteen minutes and seven seconds, for twenty seconds, a surfer descends the André Philip run. The line is that piste as OpenStreetMap records it, projected with the camera pose and the terrain. White draws behind him and fades ahead of him, so the stroke leaves the mountain with him. He weaves through five turns and leans into each one. He is the same puppet as the corners, drawn smaller because he is far up the slope.",
    stillElephant: "Between one and six in the morning, after five minutes with nothing named on the road, a pink calf fills the frame for four seconds. His turn comes every eleven minutes and one second, and only while the music is pushing. He is the one drawing that covers the road, which is why he waits for that lull. A trunk to the left, a small solid eye.",
    stillOurs: "A wooden bear stands beside the path between the roundabout and the sheepfold. The scene map measures him at 1.73 m tall and 0.64 m wide, twenty-five metres from the lens. Every two hours and a quarter a cutout taken from him at noon walks to the island in two and a half seconds, dances there for ten seconds, weeps, and shouts THIS IS MY HOME!!!!! Ninety seconds of delay hold the first dance until YouTube has opened the picture. The sculpture stays where it is, so both are in the picture together. On the island a metre is forty-three pixels, against forty-seven where he stands, and once he is dancing the cutout swells a little so he reads. A photograph of the real sculpture fades into the black band for the dance. He keeps this pace at night: the roundabout stays lit by the chalet lamp, and the double stands in that light. Night does not speed his turn.",
    stillSoleil: "When the sun is up and still behind the ridge, or the weather is cloud, overcast, fog, mist, rain, snow or storm, a child’s sun is drawn into the picture: a circle, eleven uneven rays, a smile. It sits where the real sun falls in the frame. When that point is outside the view, it sits in the corner of the sky, on the side where the sun actually is, once the sun is at least three degrees up. It breathes, about one turn in ten seconds. It is drawn before pixel and wave, so those treatments take it with the mountain.",
    stillLamp: "At night, once the sun is at or below the horizon, a picture-book lamp is drawn on the real street lamp. The pole follows the measured mast from foot to shoulder, and the bracket runs from the shoulder to the lantern the map places on the bulb. The mast is seven metres, and its length in the picture comes from that height, the distance and the lens. The glow is the lamp’s own light, turned up around the bulb, and it breathes slowly. A camera whose pole was never measured gets no lamp. It is drawn before pixel and wave, so it takes their grain.",
    stillBati: "Every seventeen minutes and forty-one seconds, for fourteen seconds, the wireframe of one building draws itself, holds, and fades. The footprint comes from OpenStreetMap and the roof height from the terrain model, both projected into the picture: the foot, then the walls, then the roof. One building at a time, the five widest in turn. The sheepfold runs past the right edge of the camera window, and the wire continues into the black band, at the place that wall would occupy if the camera saw wider.",
    stillMachine: "Every twenty-four minutes and forty-three seconds, for seven seconds, a round photograph of the Pi fills about a third of the camera window, with the words Thanks Raspberry! Two minutes of delay let YouTube open the picture before the portrait arrives. The road stays visible around the disc. The small badge in the corner stays, so the portrait reads as a second view of the same machine.",
    stillDogmazic: "Every twenty-six minutes and forty-seven seconds, for the same seven seconds, their orange dog fills that disc, with the words Thanks Dogmazic! Nine minutes of delay keep this portrait clear of the Raspberry’s turn after a restart.",
    stillReplay: "After five minutes with nothing named, a past passage comes back for ten seconds. The word replay and the date sit with the picture, so the archive stays distinct from the live road. Only a passage marked accepted can return. On air the picture is blocked into large squares; the file on disk stays sharp. It is never enlarged more than three times, and it stays within a third of the width. Ten minutes pass before another. A sung replay announces it. The moment something new is seen, the archive leaves. The card is amber.",
    stillRelief: "The 3D flyover lives on this page: the relief turns, then the view returns to the webcam angle.",
    prevPage: "Previous",
    nextPage: "Next",
    pages: "Pages",
    pageOf: (first, last, all) => `${first}–${last} of ${all}`,
    figures: "Dataviz",
    byHour: "By hour of the day",
    byDay: "By day of the week",
    figuresSpan: (days, all) => `${all} named passes over ${days} ${days > 1 ? "days" : "day"}, Paris time.`,
    figuresEmpty: "Nothing recorded yet.",
    weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    kinds: {
      vehicle: "Vehicles", person: "Pedestrians", bus: "Buses",
      fire: "Fires", plane: "Planes", other: "Other",
    },
    live: "Live webcam",
    camera: "Camera",
    cameraText: "Fixed, facing 140°.",
    pipeline: "Pipeline",
    image: "Frame",
    imageText: "1 frame/s. ffmpeg reads the HLS stream.",
    motion: "Motion",
    motionText: "OpenCV MOG2, frame scaled to 640 px. If more than 35% changes, it is light, and it is ignored. The red beacon on the summit is excluded.",
    track: "Track",
    trackText: "A compact blob, tracked for at least 3 frames.",
    class: "Class",
    classText: "YOLO11s, ONNX, on the crop only. Person, car, bus, truck.",
    plane: "Plane",
    planeText: "OpenSky. A callsign is kept only when that aircraft is in the camera’s view, close enough to be seen. Otherwise the history says it is not in the picture.",
    bus: "Bus",
    busText: "Trans'CoVe or ZOU. A single trip within ±15 min gives the route. Otherwise “Bus”, from a confidence of 0.6.",
    fire: "Fire",
    fireText: "On the slope, 5 s, area ×1.5, at least 8% warm pixels or a rising plume. Not at dusk. In rain, fog, or snow, it takes 20%.",
    rest: "Unknown",
    restText: "We don't know what it is. Every movement is shown, with its photo.",
    history: "History",
    all: "All",
    planes: "Planes",
    vehicles: "Vehicles",
    pedestrians: "Pedestrians",
    buses: "Buses",
    fires: "Fires",
    motions: "Motion",
    habits: "Habits",
    empty: "Nothing yet.",
    compare: "Weather",
    colTime: "Time",
    colPhoto: "Photo",
    colEvent: "Event",
    colPlace: "Place",
    colReading: "Reading",
    places: {
      road: "Road", roundabout: "Roundabout", parking: "Car park", path: "Path",
      meadow: "Meadow", forest: "Forest", building: "Building", slope: "Slope",
      sky: "Sky", island: "Roundabout island", scree: "Scree", playground: "Playground", pool: "Swimming pool", other: "Off the road",
    },
    reliefWake: "Click to turn the view",
    follow: "its track",
    nearestStation: "Nearest weather station:",
    from: "from",
    to: "towards",
    heading: "heading",
    climbing: "climbing",
    descending: "descending",
    notInFrame: "Not in the picture",
    colCam: "Webcam",
    colApi: "Station",
    compareEmpty: "No reading yet.",
    repoPrivate: "Source and history of every change.",
    relief: "3D view",
    reliefBack: "Webcam angle",
    reliefWide: "Full screen",
    skip: "Skip to content",
    sections: "Sections",
    theme: "Dark mode",
    themeBack: "Light mode",
    chart: [
      ["Stream", "HLS, 1 frame a second"],
      ["Motion", "MOG2 at 640 px"],
      ["Track", "3 frames, compact"],
      ["Class", "YOLO11s on the crop"],
      ["Ground", "Surface and distance"],
      ["Name", "The rules decide"],
      ["Published", "Only what is named"],
    ],
    chartJoin: ["OpenSky", "Trans'CoVe / ZOU", "OpenStreetMap"],
    chartAsk: "Asked only when naming",
    periods: { day: "Day", twilight: "Dusk", night: "Night" },
    moon: "Moon",
    wind: "Wind",
    humidity: "Humidity",
    around: "Around",
    people: "people",
    clip: "Clip",
    scoreLine: (all, read, right) =>
      `${all} published · ${read} reviewed · ${right} right as published`,
    doubt: "To judge",
    navDoubt: "To judge",
    doubtEmpty: "Nothing waiting.",
    doubtWhy: "The watcher saw these move but did not read them itself. "
      + "Its guess is written under each picture; tell it what was really there.",
    doubtCount: (all) => `${all} waiting`,
    doubtList: "Waiting for a name",
    control: "Spot check",
    controlWhy: "Drawn at random from what the site publishes. Reading these is the "
      + "only way to know how often it is right: choosing what to check would measure "
      + "what we like looking at instead.",
    claimLine: (floor, togo) => togo
      ? `At least ${floor} % right, on what has been checked. ${togo} more clean checks to claim 95 %.`
      : `At least ${floor} % right, on what has been checked.`,
    cameraFixed: "Fixed, facing",
    cameraField: "field",
    right: "Right",
    wrong: "Wrong",
    nothing: "Nothing there",
    carWord: "Car",
    vanWord: "Lorry",
    busWord: "Bus",
    walkerWord: "Walker",
    cycleWord: "Bike",
    tractorWord: "Tractor",
    confirmed: "confirmed",
    rejected: "rejected",
    fireNote: "A warm patch grew. This is not an alert.",
    weatherCodes: {
      0: "Clear", 1: "Clear", 2: "Cloudy", 3: "Overcast",
      45: "Fog", 48: "Fog", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
      61: "Light rain", 63: "Rain", 65: "Heavy rain", 71: "Light snow",
      73: "Snow", 75: "Heavy snow", 77: "Graupel", 80: "Showers", 81: "Showers",
      82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
      95: "Thunderstorm", 96: "Thunderstorm", 99: "Violent thunderstorm",
    },
  },
  fr: {
    paris: "Heure de Paris",
    weather: "Météo",
    passes: "Passages",
    namedLine: (named, habits) => `${named} nommés · ${habits} habitudes`,
    navLive: "Direct",
    onYouTube: "Voir sur YouTube",
    navHistory: "Historique",
    navFigures: "Dataviz",
    navRelief: "3D",
    navCamera: "Caméra",
    navWeather: "Météo",
    navPipeline: "Pipeline",
    navStage: "Plateau",
    navWatch: "Veille",
    navWiki: "Wiki",
    navNumbers: "Sur le flux",
    navMusic: "Dogmazic",
    watch: "La veille",
    watchLine: "OpenCV trouve ce qui a bougé. YOLO11s nomme la découpe. Une image par seconde, sur un Raspberry Pi 5 à Los Angeles. Cette lecture est le travail. L’image autour est le spectacle.",
    pipelineLead: "Un Raspberry Pi 5 à Los Angeles lit la webcam du Mont Serein, une image par seconde, et pousse l’image recomposée vers YouTube sans interruption.",
    numbers: "Sur le flux",
    numbersLead: "Dix-huit façons dont l’image change. Pixel, gris et onde partagent un tirage toutes les sept minutes, et deux tirages sur cinq laissent la photographie tranquille. Les numéros montent un par un. La nuit, ces numéros reviennent trois fois plus souvent. L’ours garde sa cadence.",
    effectColName: "Nom",
    effectColWhat: "Ce qui se passe",
    effectPixel: "Pixel",
    effectGrey: "Gris",
    effectWave: "Onde",
    effectFly: "Survol",
    effectCatch: "Prise",
    effectConsole: "Console",
    effectBear: "Ours",
    effectCarpet: "Tapis",
    effectSub: "Sous-marin",
    effectPiste: "Piste",
    effectElephant: "Éléphant",
    effectBuilding: "Bâtiment",
    effectSun: "Soleil",
    effectLamp: "Lampadaire",
    effectMachine: "Machine",
    effectDogmazic: "Dogmazic",
    effectReplay: "Rediffusion",
    effectMeet: "Rencontre",
    musicTitle: "Dogmazic",
    musicLead: "Dogmazic est une bibliothèque de musique libre. Les artistes gardent leurs droits et choisissent une licence Creative Commons : un flux peut jouer l’œuvre en public s’il nomme l’auteur, le titre, la licence et un endroit où trouver le fichier. Quatorze heures tournent ici, cent cinquante-trois morceaux, tous issus de cette bibliothèque. Quatre de ces heures sont l’album Mont Serein, écrit pour ce versant. La playlist est publique.",
    rebuild: "Reconstruit",
    rebuildLead: "ffmpeg prend la webcam à une image par seconde. OpenCV MOG2 trouve ce qui a bougé, sur une image ramenée à 640 pixels. Une tache compacte tenue trois images est découpée. YOLO11s, en ONNX, nomme seulement cette découpe. Le rectangle nommé est redessiné sur l’image d’origine, les encarts restent dans les bandes, et le cadre entier part vers YouTube. La montagne n’est jamais inventée. Elle est lue, puis remise ensemble.",
    watchMotion: "MOG2 trouve le mouvement sur la montagne.",
    watchClass: "Un petit réseau nomme la découpe : voiture, piéton, vélo, camion.",
    watchOut: "Le cadre nommé est recomposé et poussé en direct.",
    listen: "Écouter sur Dogmazic",
    radio: "Flux audio",
    radioOn: "À l’écoute",
    chipFps: "1 image / s",
    story: "La veille",
    heroLead: "Un Raspberry Pi 5 à Los Angeles lit la webcam du Mont Serein, une image par seconde, trouve le mouvement avec OpenCV, nomme ce qui a bougé avec YOLO, et reconstitue l’image en direct YouTube. La veille est le travail. Le flux est le spectacle.",
    heroMachine: "Quatre cœurs sur un bureau, à neuf mille kilomètres du col. Le Pi tient l’archive, mixe la musique, dessine les encarts et pousse le cadre entier vers YouTube en continu.",
    heroSee: "Les véhicules et les piétons sont plus avancés. La faune, les oiseaux, les avions croisés avec OpenSky et les animaux de compagnie sont encore en cours d’apprentissage. Le modèle cherche à tout voir et à tout nommer juste.",
    heroMusic: "Quatorze heures de musique libre tournent toute la journée, entièrement chez Dogmazic. Quatre de ces heures sont l’album Mont Serein, écrit pour ce versant. Cent cinquante-quatre morceaux tiennent dans une playlist publique, à un clic.",
    stage: "Sur le flux",
    stageLead: "Pixel, gris et onde partagent un tirage. Un survol filmé du relief prend la fenêtre quand la route est vide. Les autres lignes sont les numéros.",
    stillConsole: "Tant qu’un morceau joue, une console occupe toute la largeur sous l’image : la pochette qui vient de finir, celle qui joue, et les deux suivantes. Avec le morceau en cours, l’artiste, le titre, la licence et le domaine du fichier, le crédit qu’un flux peut montrer là où rien ne se clique. Un égaliseur suit la musique. Le numéro de cette version reste écrit là pendant toute la session.",
    stillPixel: "Toutes les sept minutes le flux tire un traitement parmi cinq cases, et deux de ces cases sont vides, donc la photographie reste souvent elle-même. Quand le tirage est le pixel, l’image se réduit à vingt-six colonnes puis se regrossit au plus proche, pendant vingt secondes. Elle monte et redescend en trois secondes et demie à chaque bout. Vingt-six colonnes laissent la route et la crête reconnaissables. Pixel, gris et onde ne s’empilent pas. Pendant quatre secondes après un passage nommé, ils se taisent, pour que la chose dans le rectangle reste une chose qu’on peut regarder.",
    stillGris: "Le même tirage, les mêmes vingt secondes, le même fondu. La couleur se mélange à la luminance perçue : un ciel bleu et un versant vert de même moyenne arithmétique n’ont pas la même clarté à l’œil, et c’est cette clarté que le mélange suit. À pleine force le versant est gris, puis la couleur revient.",
    stillOndule: "Le même tirage. Vingt-huit bandes horizontales glissent de côté, jusqu’à trois pour cent de la largeur, comme une image sous l’eau. Le Pi décale des lignes entières. Recalculer chaque pixel serait trop lourd pendant qu’il encode.",
    stillFly: "Après cinq minutes sans rien de nommé, et tant qu’aucune rediffusion n’est à l’écran, un survol filmé du relief prend la fenêtre de la caméra. Le jour, il joue deux minutes, un JPEG par image, un aller-retour complet, donc la boucle se raccorde sur le point de vue de la webcam. La nuit, il tient une minute et demie sur l’image du milieu, le point le plus loin, celui d’où le versant se lit de côté. Il s’arrête dès que la veille voit quelque chose. Une demi-heure passe avant le suivant. Le direct reste dans une petite fenêtre. Les danseurs restent absents de cette vue. Le Pi ouvre des images qu’il a déjà.",
    stillEclat: "Une prise, c’est un nom auquel la veille se fie pendant que la chose est encore dans l’image : une voiture, un piéton, un vélo, un bus, un camion, un avion. Le flux a quelques secondes de retard sur la veille, donc la fête attend que le sujet soit à l’écran et que le rectangle l’entoure. GOOD CATCH! traverse alors la montagne en vert pendant une seconde et demie. Un éclair blanc s’éteint en une demi-seconde. Le nom s’écrit sous les mots, parce que l’acclamation seule ne dit pas ce qui a été pris. En même temps, la bande autour de la fenêtre caméra s’allume de la couleur de ce genre de passage, pendant trois secondes et demie, et le nom s’écrit en grand sous l’image, par-dessus le câble et le haut de la console. Pixel, gris et onde se taisent pendant quatre secondes, pour que ce qui est passé reste regardable. La montagne reste la photographie.",
    stillRencontre: "Deux pantins se tiennent dans les coins bas de la fenêtre quand la musique pousse, à demi transparents, pour que le versant reste devant. Environ toutes les sept minutes ils quittent ces coins, se rejoignent au milieu de la fenêtre, y restent six secondes, et rentrent, quatre secondes à l’aller comme au retour. Entre deux rencontres ils sortent aussi quelques secondes dans les bandes noires. Pendant un survol, ils restent hors du relief.",
    stillTapis: "Toutes les six minutes et trente-sept secondes, quand la musique pousse, un tapis volant traverse le cadre entier en quatorze secondes, bandes noires comprises. Il suit la crête, donc il passe au-dessus du sommet. Le personnage dessus est le même pantin que les deux des coins. Si un autre numéro tient déjà la scène au début de ce tour, le tapis attend le suivant.",
    stillMarin: "Toutes les huit minutes et quarante-trois secondes, le sous-marin jaune de benoit-prieur.fr traverse le ciel en vingt-deux secondes. Il suit la crête et tangue d’un dixième de sa hauteur, deux fois et demie pendant la traversée. Il reste au-dessus de la route, donc il passe à son tour que la musique pousse ou que le versant soit calme. Si le dessin manque sur le Pi, la traversée n’a pas lieu.",
    stillPiste: "Toutes les treize minutes et sept secondes, pendant vingt secondes, un surfeur descend la piste André Philip. Le trait est cette piste telle qu’OpenStreetMap la connaît, projetée avec la pose de la caméra et le terrain. Le blanc se dessine derrière lui et s’efface devant lui, donc le trait quitte la montagne avec lui. Il louvoie sur cinq virages et se couche dans chacun. C’est le même pantin que ceux des coins, dessiné plus petit parce qu’il est loin sur le versant.",
    stillElephant: "Entre une heure et six heures du matin, après cinq minutes sans rien de nommé sur la route, un éléphanteau rose occupe tout le cadre pendant quatre secondes. Son tour revient toutes les onze minutes et une seconde, et seulement quand la musique pousse. C’est le dessin qui couvre la route, et c’est pour ça qu’il attend ce creux. Une trompe à gauche, un petit œil plein.",
    stillOurs: "Un ours de bois se tient au bord du chemin, entre le rond-point et la bergerie. La carte de scène le mesure à 1,73 m de haut et 0,64 m de large, à vingt-cinq mètres de l’objectif. Toutes les deux heures et quart, une découpe prise sur lui en plein midi marche jusqu’à l’îlot en deux secondes et demie, y danse dix secondes, pleure, et crie THIS IS MY HOME!!!!! Quatre-vingt-dix secondes de retard gardent la première danse pour après l’ouverture de l’image chez YouTube. La sculpture reste à sa place, donc les deux sont dans l’image ensemble. Sur l’îlot un mètre vaut quarante-trois pixels, contre quarante-sept là où il se tient, et une fois qu’il danse la découpe enfle un peu pour qu’on le lise. Une photographie de la vraie sculpture apparaît en fondu dans la bande noire pendant la danse. Il garde cette cadence la nuit : le rond-point reste éclairé par le lampadaire du chalet, et le double se tient dans cette lumière. La nuit n’accélère pas son tour.",
    stillSoleil: "Quand le soleil est levé et encore derrière la crête, ou que le temps est nuageux, couvert, brouillard, brume, pluie, neige ou orage, un soleil d’enfant est dessiné dans l’image : un rond, onze rayons inégaux, un sourire. Il se pose là où le vrai soleil tombe dans le cadre. Quand ce point est hors du champ, il se pose dans le coin du ciel, du côté où le soleil se trouve vraiment, dès qu’il est à au moins trois degrés. Il respire, environ un tour en dix secondes. Il est dessiné avant le pixel et l’onde, donc ces traitements l’emportent avec la montagne.",
    stillLamp: "La nuit, dès que le soleil est à l’horizon ou en dessous, un lampadaire de livre d’images est dessiné sur le vrai. Le mât suit le poteau mesuré, du pied à l’épaule, et la potence va de l’épaule à la lanterne que la carte pose sur l’ampoule. Le mât fait sept mètres, et sa longueur dans l’image vient de cette hauteur, de la distance et de l’objectif. La lueur est celle de la lampe, remontée autour de l’ampoule, et elle respire lentement. Une caméra dont le poteau n’a pas été mesuré n’a pas de lampadaire. Il est dessiné avant le pixel et l’onde, donc il prend leur grain.",
    stillBati: "Toutes les dix-sept minutes et quarante et une secondes, pendant quatorze secondes, le fil de fer d’un bâtiment se dessine, tient, puis s’efface. L’emprise vient d’OpenStreetMap et la hauteur du toit du modèle de terrain, les deux projetés dans l’image : le pied, puis les murs, puis le toit. Un bâtiment à la fois, les cinq plus larges à tour de rôle. La bergerie dépasse le bord droit de la fenêtre, et le fil continue dans la bande noire, à l’endroit où ce mur serait si la caméra voyait plus large.",
    stillMachine: "Toutes les vingt-quatre minutes et quarante-trois secondes, pendant sept secondes, une photographie ronde du Pi occupe environ un tiers de la fenêtre, avec les mots Thanks Raspberry! Deux minutes de retard laissent à YouTube le temps d’ouvrir l’image avant le portrait. La route reste visible autour du disque. Le petit badge du coin reste, donc le portrait se lit comme une seconde vue de la même machine.",
    stillDogmazic: "Toutes les vingt-six minutes et quarante-sept secondes, pendant les mêmes sept secondes, leur chien orange occupe ce disque, avec les mots Thanks Dogmazic! Neuf minutes de retard écartent ce portrait du tour du Raspberry après un redémarrage.",
    stillReplay: "Après cinq minutes sans rien de nommé, un passage ancien revient pendant dix secondes. Le mot replay et la date accompagnent l’image, donc l’archive reste distincte de la route en direct. Seul un passage marqué accepté peut revenir. À l’antenne l’image est en gros carrés ; le fichier sur le disque reste net. Elle n’est jamais agrandie plus de trois fois, et elle tient dans un tiers de la largeur. Dix minutes passent avant la suivante. Un replay chanté l’annonce. Dès que quelque chose de nouveau est vu, l’archive s’en va. La carte est ambre.",
    stillRelief: "Le survol 3D est sur cette page : le relief tourne, puis la vue revient à l’angle de la webcam.",
    prevPage: "Précédent",
    nextPage: "Suivant",
    pages: "Pages",
    pageOf: (first, last, all) => `${first}–${last} sur ${all}`,
    figures: "Dataviz",
    byHour: "Par heure de la journée",
    byDay: "Par jour de la semaine",
    figuresSpan: (days, all) => `${all} passages nommés sur ${days} jour${days > 1 ? "s" : ""}, heure de Paris.`,
    figuresEmpty: "Rien d'enregistré pour l'instant.",
    weekdays: ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
    kinds: {
      vehicle: "Véhicules", person: "Piétons", bus: "Bus",
      fire: "Feux", plane: "Avions", other: "Autres",
    },
    live: "Webcam en direct",
    camera: "Caméra",
    cameraText: "Fixe, vers 140°.",
    pipeline: "Pipeline",
    image: "Image",
    imageText: "1 image/s. ffmpeg lit le flux HLS.",
    motion: "Mouvement",
    motionText: "OpenCV MOG2, image ramenée à 640 px. Si plus de 35 % change, c’est la lumière, on ignore. La balise rouge du sommet est exclue.",
    track: "Suivi",
    trackText: "Une tache compacte, suivie au moins de 3 images.",
    class: "Classe",
    classText: "YOLO11s, en ONNX, seulement sur le rectangle. Personne, voiture, bus, camion.",
    plane: "Avion",
    planeText: "OpenSky. L’indicatif n’est gardé que si l’avion est dans le champ, assez près pour être vu. Sinon l’historique dit qu’il n’est pas dans l’image.",
    bus: "Bus",
    busText: "Trans'CoVe ou ZOU. Une seule course à ±15 min donne la ligne. Sinon « Bus », à partir d’une confiance de 0,6.",
    fire: "Feu",
    fireText: "Sur la pente, 5 s, surface ×1,5, au moins 8 % de pixels chauds ou un panache qui monte. Au crépuscule, non. Sous la pluie, le brouillard ou la neige, il faut 20 %.",
    rest: "Inconnu",
    restText: "On ne sait pas ce que c’est. Chaque mouvement est affiché, avec sa photo.",
    history: "Historique",
    all: "Tout",
    planes: "Avions",
    vehicles: "Véhicules",
    pedestrians: "Piétons",
    buses: "Bus",
    fires: "Incendies",
    motions: "Mouvements",
    habits: "Habitudes",
    empty: "Rien pour l’instant.",
    compare: "Météo",
    colTime: "Heure",
    colPhoto: "Photo",
    colEvent: "Événement",
    colPlace: "Lieu",
    colReading: "Lecture",
    places: {
      road: "Chaussée", roundabout: "Rond-point", parking: "Parking", path: "Sentier",
      meadow: "Prairie", forest: "Forêt", building: "Bâti", slope: "Pente",
      sky: "Ciel", island: "Îlot central", scree: "Éboulis", playground: "Aire de jeux", pool: "Piscine", other: "Hors chaussée",
    },
    reliefWake: "Cliquer pour tourner la vue",
    follow: "sa trace",
    nearestStation: "Station météo la plus proche :",
    from: "de",
    to: "vers",
    heading: "cap",
    climbing: "en montée",
    descending: "en descente",
    notInFrame: "Pas dans l'image",
    colCam: "Webcam",
    colApi: "Station",
    compareEmpty: "Pas encore de relevé.",
    repoPrivate: "Le code et l’histoire de chaque changement.",
    relief: "Vue 3D",
    reliefBack: "Angle webcam",
    reliefWide: "Plein écran",
    skip: "Aller au contenu",
    sections: "Sections",
    theme: "Mode sombre",
    themeBack: "Mode clair",
    chart: [
      ["Flux", "HLS, une image par seconde"],
      ["Mouvement", "MOG2 à 640 px"],
      ["Piste", "3 images, compacte"],
      ["Classe", "YOLO11s sur la découpe"],
      ["Sol", "Surface et distance"],
      ["Nom", "Les règles tranchent"],
      ["Publié", "Rien que le nommé"],
    ],
    chartJoin: ["OpenSky", "Trans'CoVe / ZOU", "OpenStreetMap"],
    chartAsk: "Interrogé seulement pour nommer",
    periods: { day: "Jour", twilight: "Crépuscule", night: "Nuit" },
    moon: "Lune",
    wind: "Vent",
    humidity: "Humidité",
    around: "Autour",
    people: "personnes",
    clip: "Extrait",
    scoreLine: (all, read, right) =>
      `${all} publications · ${read} relues · ${right} juste${right > 1 ? "s" : ""} du premier coup`,
    doubt: "À trancher",
    navDoubt: "À trancher",
    doubtEmpty: "Rien en attente.",
    doubtWhy: "La veille a vu bouger ces choses sans les lire elle-même. "
      + "Sa supposition est écrite sous chaque photo ; dites-lui ce qu'il y avait vraiment.",
    doubtCount: (all) => `${all} en attente`,
    doubtList: "En attente d'un nom",
    control: "Contrôle",
    controlWhy: "Tirées au hasard dans ce que le site publie. Les lire est le seul "
      + "moyen de savoir à quelle fréquence il a raison : choisir quoi vérifier "
      + "mesurerait ce qu'on aime regarder.",
    claimLine: (floor, togo) => togo
      ? `Au moins ${floor} % de juste, sur ce qui a été contrôlé. Encore ${togo} contrôles sans faute pour affirmer 95 %.`
      : `Au moins ${floor} % de juste, sur ce qui a été contrôlé.`,
    cameraFixed: "Fixe, cap",
    cameraField: "champ",
    right: "Juste",
    wrong: "Faux",
    nothing: "Rien",
    carWord: "Voiture",
    vanWord: "Camion",
    busWord: "Bus",
    walkerWord: "Piéton",
    cycleWord: "Vélo",
    tractorWord: "Tracteur",
    confirmed: "validé",
    rejected: "rejeté",
    fireNote: "Tache chaude qui a grossi. Ce n’est pas une alerte.",
    weatherCodes: {
      0: "Ciel dégagé", 1: "Dégagé", 2: "Nuageux", 3: "Couvert",
      45: "Brouillard", 48: "Brouillard", 51: "Bruine", 53: "Bruine", 55: "Bruine",
      61: "Pluie légère", 63: "Pluie", 65: "Forte pluie", 71: "Neige légère",
      73: "Neige", 75: "Forte neige", 77: "Grésil", 80: "Averses", 81: "Averses",
      82: "Fortes averses", 85: "Averses de neige", 86: "Averses de neige",
      95: "Orage", 96: "Orage", 99: "Orage violent",
    },
  },
};

const LABELS = {
  "Voiture": "Car",
  "Voiture et piéton": "Car and pedestrian",
  "Camion": "Truck",
  "Véhicule": "Vehicle",
  "Camping-car": "Camper van",
  "Incendie": "Fire",
  "Habitude du cadrage": "Habit of the frame",
  "Mouvement": "Motion",
  "Mouvement sur la route": "Motion on the road",
  "Mouvement dans le ciel": "Motion in the sky",
  "Masse dans le ciel": "Mass in the sky",
  "Point dans le ciel": "Point in the sky",
  "Presque immobile": "Almost still",
  "Vu trop brièvement": "Seen too briefly",
  "Véhicule incertain": "Uncertain vehicle",
  "Piéton": "Pedestrian",
  "Piétons": "Pedestrians",
  "Vélo": "Bicycle",
  "Tracteur": "Tractor",
  "Moto": "Motorbike",
  "Deux-roues": "Two-wheeler",
  "Piétons et une voiture": "Pedestrians and a car",
  "Voiture et piétons": "A car and pedestrians",
  "Deux véhicules et un piéton": "Two vehicles and a pedestrian",
  "Soleil bas dans les arbres": "Low sun in the trees",
  "Mouvement devant le relief": "Motion against the hillside",
  "Chien": "Dog",
  "Cheval": "Horse",
  "Piétons doublés par une voiture": "Pedestrians overtaken by a car",
  "Avion non identifié": "Unidentified aircraft",
  "Voiture blanche": "White car",
  "Estafette": "Van",
  "Camionnette blanche": "White van",
  "Voiture avec carriole": "Car with a trailer",
  "Repère éclairé": "Lit landmark",
  "Mouvement hors chaussée": "Motion off the road",
  "Tache trop large": "Patch too wide",
  "Départ de feu": "Fire starting",
  "Masse sur la pente": "Mass on the slope",
  "Camionnette": "Van",
  "Voiture garée": "Parked car",
  "Lueur du soir": "Evening glow",
  "Simulation : incendie": "Simulation: fire",
  "Simulation : départ de feu": "Simulation: fire starting",
  "Motif sur la chaussée": "Pattern on the roadway",
  "Décor de l’îlot": "Roundabout island furniture",
  "Lueur dans la météo": "Glow in the weather",
  // Les motifs de refus, lus sous les photos de la page à trancher.
  "Rien de reconnu": "Nothing recognised",
  "Rien de reconnu sur la découpe": "Nothing recognised in the crop",
  "Rien de reconnu à cet endroit": "Nothing recognised at that spot",
  "Plusieurs lectures à cet endroit": "Several readings at that spot",
  "Lecture ambiguë": "Ambiguous reading",
  "Véhicule non nommé": "Unnamed vehicle",
  "Immobile dans le ciel": "Still in the sky",
  "Immobile sur la pente": "Still on the slope",
  "Toujours au même endroit": "Always at the same spot",
  "Trop petit": "Too small",
  "Devant le relief": "Against the hillside",
  "Au bord de l'image": "At the edge of the frame",
  "Décor connu": "Known furniture",
  "Décor de l'îlot": "Roundabout island furniture",
  "Balise du sommet": "Summit beacon",
  "Brouillard": "Fog",
  "Brume": "Haze",
  "Nuage": "Cloud",
  "Panache de nuit": "Night plume",
  "Phares": "Headlights",
  "Forme inattendue": "Unexpected shape",
  "Hors chaussée": "Off the road",
  "Dans le champ": "In the frame",
  "Horaire": "Timetable",
  "Tache chaude qui grossit": "Warm patch growing",
};

let lang = localStorage.getItem("ventoux-lang") === "fr" ? "fr" : "en";
let weatherNow = null;
let bulletin = null;

const SKY = {
  "ciel dégagé": "Clear",
  "peu nuageux": "Partly cloudy",
  "couvert": "Overcast",
  "brouillard": "Fog",
  "pluie": "Rain",
  "neige": "Snow",
  "orage": "Thunderstorm",
  "nuit": "Night",
};
let counts = null;

function t(key) {
  return COPY[lang][key];
}

function locale() {
  return lang === "fr" ? "fr-FR" : "en-GB";
}

// The 3D view is a separate module and must not keep a second copy of the
// wording: one dictionary, or the same place ends up named two ways.
const THEME_KEY = "ventoux-theme";
let theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";

const HASH = "#FREETECHNORADIO";
const HASH_GLYPHS = {
  "#": ["01010", "11111", "01010", "11111", "01010", "00000", "00000"],
  A: ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
  C: ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
  D: ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
  E: ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
  F: ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
  H: ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
  I: ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
  N: ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
  O: ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
  R: ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
  T: ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
};

function hashTile(color) {
  const cell = 3;
  const gap = 1;
  const stride = 6;
  const step = cell + gap;
  const tile = document.createElement("canvas");
  tile.width = HASH.length * stride * step - gap + step * 2;
  tile.height = 7 * step - gap;
  const ctx = tile.getContext("2d");
  ctx.fillStyle = color;
  for (let i = 0; i < HASH.length; i += 1) {
    const rows = HASH_GLYPHS[HASH[i]] || [];
    for (let y = 0; y < rows.length; y += 1) {
      for (let x = 0; x < rows[y].length; x += 1) {
        if (rows[y][x] === "1") {
          ctx.fillRect((i * stride + x) * step, y * step, cell, cell);
        }
      }
    }
  }
  return tile;
}

function paintHash() {
  const color = getComputedStyle(document.documentElement).getPropertyValue("--pine").trim() || "#1e3a30";
  const tile = hashTile(color);
  document.querySelectorAll("canvas.hash-title").forEach((canvas) => {
    const scale = Math.max(2, Math.min(3, Math.floor((canvas.parentElement?.clientWidth || 720) / tile.width)));
    canvas.width = tile.width * scale;
    canvas.height = tile.height * scale;
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(tile, 0, 0, canvas.width, canvas.height);
  });
  document.querySelectorAll("canvas.hash-strip").forEach((canvas) => {
    const side = canvas.classList.contains("hash-side");
    const wide = Math.max(1, canvas.clientWidth);
    const high = Math.max(1, canvas.clientHeight);
    canvas.width = wide;
    canvas.height = high;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, wide, high);
    ctx.imageSmoothingEnabled = false;
    if (side) {
      ctx.translate(wide / 2, high / 2);
      ctx.rotate(-Math.PI / 2);
      const run = high;
      const mid = -tile.height / 2;
      for (let x = -run / 2; x < run / 2; x += tile.width) {
        ctx.drawImage(tile, x, mid);
      }
    } else {
      const mid = Math.round((high - tile.height) / 2);
      for (let x = 0; x < wide; x += tile.width) {
        ctx.drawImage(tile, x, mid);
      }
    }
  });
}

function applyTheme() {
  document.documentElement.dataset.theme = theme;
  const knob = document.getElementById("theme");
  if (knob) {
    const next = theme === "dark" ? t("themeBack") : t("theme");
    knob.textContent = theme === "dark" ? "☀" : "◐";
    knob.title = next;
    knob.setAttribute("aria-label", next);
    knob.setAttribute("aria-pressed", String(theme === "dark"));
  }
  paintHash();
}

document.getElementById("theme")?.addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, theme);
  applyTheme();
});
document.addEventListener("ventoux-lang", applyTheme);
applyTheme();
if (window.ResizeObserver) {
  document.querySelectorAll(".hash-frame").forEach((frame) => {
    new ResizeObserver(() => paintHash()).observe(frame);
  });
}
window.addEventListener("resize", paintHash);

window.ventoux = {
  locale,
  place: (key) => t("places")[key] || key,
  period: (key) => t("periods")[key] || key,
};

function drawChart() {
  const chart = document.getElementById("chart");
  if (!chart) return;
  const steps = t("chart").map(([name, note], turn) => {
    const last = turn === t("chart").length - 1 ? " out" : "";
    return `<div class="step${last}"><b>${name}</b><span>${note}</span></div>`;
  });
  // On their own line, and never in the chain. These are asked at the naming
  // step and nowhere else: a callsign or a timetable never decides that
  // something moved, only what to call it once it has.
  const joins = t("chartJoin").map((name) => `<span class="join">${name}</span>`);
  chart.innerHTML = `<div class="flow">${steps.join("")}</div>`
    + `<p class="asks"><span class="lab">${t("chartAsk")}</span>${joins.join("")}</p>`;
}

function applyLang() {
  queueMicrotask(() => document.dispatchEvent(new CustomEvent("ventoux-lang")));
  document.documentElement.lang = lang;
  drawChart();
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const value = t(node.dataset.i18n);
    if (typeof value === "string") node.textContent = value;
  });
  document.querySelectorAll("[data-i18n-title]").forEach((node) => {
    node.title = t(node.dataset.i18nTitle);
    node.setAttribute("aria-label", t(node.dataset.i18nTitle));
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nAria));
  });
  document.querySelectorAll(".langs button").forEach((button) => {
    button.classList.toggle("on", button.dataset.lang === lang);
  });
  tick();
  paintCamera();
  paintWeather();
  paintBulletin();
  paintCounts();
  render();
  paintFigures();
  paintSequence();
}

document.querySelectorAll(".langs button").forEach((button) => {
  button.addEventListener("click", () => {
    lang = button.dataset.lang === "fr" ? "fr" : "en";
    localStorage.setItem("ventoux-lang", lang);
    applyLang();
  });
});

function km(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(h));
}

const station = STATIONS.slice().sort((a, b) => km(CAMERA, a) - km(CAMERA, b))[0];

function tick() {
  const clock = document.querySelector("#clock");
  if (!clock) return;
  const now = new Date();
  clock.textContent = now.toLocaleTimeString(locale(), {
    timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit",
  });
  const date = document.querySelector("#clock-date");
  if (date) {
    date.textContent = now.toLocaleDateString(locale(), {
      timeZone: "Europe/Paris", weekday: "short", day: "numeric", month: "short",
    });
  }
}

function mapLink(spot) {
  return `https://www.openstreetmap.org/?mlat=${spot.lat}&mlon=${spot.lon}#map=14/${spot.lat}/${spot.lon}`;
}

function escapeText(word) {
  return String(word).replace(/[&<>"]/g, (mark) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[mark]));
}

function stationLabel() {
  // The camera before the station. The forecast is modelled on a grid whose
  // ground here lies a thousand metres below the lens, so it answers for the
  // valley: it read "clear" from dusk to dawn on 26 September while the crest
  // of the Ventoux was nowhere in the picture. The bulletin is read off the
  // webcam itself, and where the two disagree the webcam is the one standing
  // on the mountain.
  if (bulletin && bulletin.webcam && bulletin.webcam !== "nuit") return skyText(bulletin.webcam);
  return weatherNow ? t("weatherCodes")[weatherNow.code] || "" : "";
}

function paintWeather() {
  // Everything about the weather now reads in the weather section: which
  // station, how far, the wind, the humidity. The bar at the top keeps the one
  // line anybody glances at, and the temperature carries the sky with it
  // rather than trailing a note underneath. Four stacked lines up there cost
  // fifty pixels of every section on the page, every time anyone scrolled.
  const more = document.querySelector("#view-air");
  const weather = document.querySelector("#weather");
  if (weatherNow && weather) {
    const sky = stationLabel();
    weather.textContent =
      [Number.isFinite(weatherNow.temp) ? `${weatherNow.temp} °C` : "—", sky].filter(Boolean).join(" · ");
  }
  if (more && weatherNow) {
    more.textContent = [
      Number.isFinite(weatherNow.wind) ? `${t("wind")} ${weatherNow.wind} km/h` : "",
      Number.isFinite(weatherNow.humidity) ? `${t("humidity")} ${weatherNow.humidity} %` : "",
    ].filter(Boolean).join(" · ");
  }
  paintBulletin();
}

function skyText(value) {
  if (!value) return "";
  if (lang === "fr") return value.charAt(0).toUpperCase() + value.slice(1);
  return SKY[value] || value;
}

function paintBulletin() {
  const words = document.querySelector("#view-words");
  const when = document.querySelector("#view-when");
  const photo = document.querySelector("#view-photo");
  const shot = document.querySelector("#view-shot");
  const moon = document.querySelector("#view-moon");
  const place = document.querySelector("#view-station");
  if (!words || !when || !photo || !place) return;
  if (!bulletin || !bulletin.t) {
    words.textContent = t("compareEmpty");
    when.textContent = "";
    if (shot) shot.hidden = true;
    // Still say who the station is. It used to be named in the bar at the top
    // as well, and with that gone this is the only place it appears: emptying
    // the line would take the reading's source off the page altogether.
    place.innerHTML = stationLine();
    return;
  }
  when.textContent = new Date(bulletin.t).toLocaleString(locale(), {
    timeZone: "Europe/Paris", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
  words.textContent = [
    t("periods")[bulletin.period] || "",
    bulletin.moon ? t("moon") : "",
    skyText(bulletin.webcam),
  ].filter(Boolean).join(" · ");
  if (bulletin.photo) {
    photo.src = `${bulletin.photo}?t=${encodeURIComponent(bulletin.t)}`;
    if (shot) shot.hidden = false;
  }
  // The words say there is a moon; this says which of the bright specks it is.
  // The watcher already found the disc to say so, and kept where it was.
  const at = bulletin.moon_at;
  if (moon) {
    moon.hidden = !at;
    if (at) {
      moon.style.left = `${at.cx * 100}%`;
      moon.style.top = `${at.cy * 100}%`;
      moon.style.width = `${Math.max(at.r * 2 * 100, 4)}%`;
      moon.title = t("moon");
    }
  }
  // Who is speaking, and from how far. A reading that disagrees with the
  // picture above it is only worth arguing with once you know it was taken
  // twenty-two kilometres away and eleven hundred metres lower.
  const reading = [
    Number.isFinite(bulletin.temp_c) ? `${bulletin.temp_c} °C` : "",
    skyText(bulletin.api) || stationLabel(),
  ].filter(Boolean).join(" · ");
  place.innerHTML = stationLine(reading);
}

function stationLine(reading) {
  return `${t("nearestStation")} <a class="out" href="${mapLink(station)}" target="_blank" rel="noopener">${escapeText(station.name)}</a>`
    + ` · ${escapeText(`${Math.round(km(CAMERA, station))} km`)}`
    + (reading ? ` · ${escapeText(reading)}` : "");
}

async function loadView() {
  try {
    const response = await fetch("data/view.json", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    bulletin = payload.last || null;
    // Not paintBulletin alone: the bar at the top quotes the webcam too now.
    paintWeather();
  } catch (_) {
    /* The card fills once the watcher has read the sky. */
  }
}

async function loadWeather() {
  paintWeather();
  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${station.lat}&longitude=${station.lon}`
      + "&current=temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m&timezone=Europe/Paris";
    const data = await fetch(url, { cache: "no-store" }).then((response) => response.json());
    const current = data.current || {};
    weatherNow = {
      temp: Math.round(current.temperature_2m),
      code: current.weather_code,
      humidity: Math.round(current.relative_humidity_2m),
      wind: Math.round(current.wind_speed_10m),
    };
    paintWeather();
  } catch (_) {
    const weather = document.querySelector("#weather");
    if (weather) weather.textContent = "—";
  }
}

const STREAM = "https://visionenvironnement.quanteec.com/contents/encodings/live/78e0f372-db6f-420e-746c-7561-6665-64-b4d7-fc979b816efed/master.m3u8";
const FALLBACK = "https://s1.vision-environnement.com/live/modules/timelapse/timelapse/montserein.mp4";

const video = document.querySelector("#player");
const direct = document.querySelector("#direct");
const surYouTube = document.querySelector("#sur-youtube");

// The raw camera, kept as the way back. It is only ever shown if the broadcast
// cannot be named: a page about watching a mountain that shows no mountain has
// failed, whatever the reason.
let secours = null;

function showCamera() {
  if (!video.hidden) return;
  direct.hidden = true;
  video.hidden = false;
  if (window.Hls && Hls.isSupported()) {
    secours = new Hls();
    secours.loadSource(STREAM);
    secours.attachMedia(video);
    secours.on(Hls.Events.ERROR, (_, data) => {
      if (data.fatal) video.src = FALLBACK;
    });
  } else {
    video.src = video.canPlayType("application/vnd.apple.mpegurl") ? STREAM : FALLBACK;
  }
}

// And stopped for good when the broadcast comes back. Hidden is not stopped:
// a <video> behind display:none keeps pulling its segments, and a visitor who
// opened the page during an outage would have gone on paying for a second
// stream they were no longer being shown.
function hideCamera() {
  if (video.hidden) return;
  video.pause();
  if (secours) {
    secours.destroy();
    secours = null;
  }
  video.removeAttribute("src");
  video.load();
  video.hidden = true;
}

// Never written into the page. YouTube closes a broadcast and opens another
// whenever the stream restarts, and the number changes with it; a page holding
// yesterday's number shows a finished recording and says "live" above it. The
// watch writes the current one into data/direct.json, so the page asks.
let diffusion = "";

async function suisLeDirect() {
  let fiche = null;
  try {
    fiche = await fetch("data/direct.json", { cache: "no-store" }).then((r) => r.json());
  } catch (_) {
    if (!diffusion) showCamera();
    return;
  }
  const numero = String(fiche.video || "");
  if (!/^[\w-]{11}$/.test(numero)) {
    if (!diffusion) showCamera();
    return;
  }
  if (fiche.chaine && surYouTube) {
    surYouTube.href = `https://www.youtube.com/channel/${fiche.chaine}/live`;
  }
  // Only when it has actually changed. Reassigning src reloads the player, and
  // a check every few minutes would restart the stream under the viewer.
  if (numero === diffusion) return;
  diffusion = numero;
  const lance = new URLSearchParams(location.search).get("play") === "1";
  direct.src = `https://www.youtube.com/embed/${numero}?autoplay=1&mute=${lance ? 0 : 1}&playsinline=1&rel=0&enablejsapi=1&origin=${encodeURIComponent(location.origin)}`;
  hideCamera();
  direct.hidden = false;
  if (lance) demarreLeDirect();
}

function commandeDirect(fonction, args) {
  if (!direct || direct.hidden || !direct.contentWindow) return;
  direct.contentWindow.postMessage(JSON.stringify({
    event: "command", func: fonction, args: args || [],
  }), "*");
}

function demarreLeDirect() {
  let tours = 0;
  const bat = setInterval(() => {
    tours += 1;
    commandeDirect("playVideo");
    commandeDirect("unMute");
    if (tours > 12) clearInterval(bat);
  }, 700);
}

suisLeDirect();
// The watch refreshes the file every few minutes; a tab left open all night
// should follow the broadcast that replaced the one it opened on.
setInterval(suisLeDirect, 5 * 60 * 1000);

const list = document.querySelector("#list");
const empty = document.querySelector("#empty");
let events = [];
let filter = "all";
// A page of the log, not the whole of it. Eight thousand passes make a table
// forty thousand pixels tall, which is a section no reader ever reaches the
// foot of and a page no browser lays out quickly.
const PER_PAGE = 25;
let page = 0;

const loupe = document.querySelector("#loupe");
const loupeImg = loupe?.querySelector("img.frame");
const loupeNear = loupe?.querySelector("img.near");

function moveLoupe(event) {
  const pad = 12;
  const box = loupe.getBoundingClientRect();
  let x = event.clientX + 20;
  let y = event.clientY - box.height / 2;
  if (x + box.width > window.innerWidth - pad) x = event.clientX - box.width - 20;
  if (y < pad) y = pad;
  if (y + box.height > window.innerHeight - pad) y = Math.max(pad, window.innerHeight - box.height - pad);
  loupe.style.left = `${x}px`;
  loupe.style.top = `${y}px`;
}

// Les trois listes de vues, et elles seules. La loupe n'écoutait que
// l'historique, si bien que les cartes à juger — les seules où l'on ait
// vraiment besoin de regarder de près, puisqu'on y répond — en étaient
// privées. Nommer les conteneurs plutôt que les classes : « shot » est aussi
// la vue en direct et « card » est aussi la fiche du relief, deux images qu'on
// ne veut pas voir surgir au-dessus d'elles-mêmes. Écouté sur le document
// parce que les listes sont réécrites à chaque page tournée.
const AGRANDIR = "#list .shot img, #doubt-list img, #control-list img";

document.addEventListener("mouseover", (event) => {
  if (!loupe || !loupeImg) return;
  const img = event.target.closest?.(AGRANDIR);
  if (!img) return;
  loupeImg.src = img.src;
  // Et la découpe à côté, quand il y en a une : agrandir la vignette ne fait
  // pas apparaître les détails qu'elle n'a pas, la découpe les a gardés.
  const near = img.dataset.big;
  loupeNear.hidden = !near;
  if (near) loupeNear.src = near;
  loupe.hidden = false;
  moveLoupe(event);
});
document.addEventListener("mousemove", (event) => {
  if (!loupe || loupe.hidden) return;
  if (event.target.closest?.(AGRANDIR)) moveLoupe(event);
});
document.addEventListener("mouseout", (event) => {
  if (!loupe) return;
  if (event.target.closest?.(AGRANDIR)) loupe.hidden = true;
});

document.querySelectorAll(".filters button").forEach((button) => {
  button.addEventListener("click", () => {
    filter = button.dataset.filter;
    page = 0;
    document.querySelectorAll(".filters button").forEach((item) => item.classList.toggle("on", item === button));
    render();
  });
});

document.querySelector("#doubt-pager")?.addEventListener("click", (hit) => {
  const step = Number(hit.target?.dataset?.step || 0);
  if (!step) return;
  doubtPage += step;
  paintDoubt();
  document.querySelector("#doubt")?.scrollIntoView({ behavior: "smooth", block: "start" });
});

document.querySelector("#pager")?.addEventListener("click", (hit) => {
  const step = hit.target.closest("button")?.dataset.step;
  if (!step) return;
  page += Number(step);
  render();
  // Back to the head of the log, otherwise turning the page leaves the reader
  // looking at the foot of a table whose rows have all changed under them.
  document.querySelector("#log")?.scrollIntoView({ behavior: "smooth", block: "start" });
});

function who(info) {
  // The airline and flight number when the code is one we know, the raw
  // callsign otherwise. Never both: repeating AAL746 after "American Airlines
  // 746" tells the reader nothing they have not just read.
  if (info.operator && info.flight) return escapeText(`${info.operator} ${info.flight}`);
  return escapeText(info.callsign || "OpenSky");
}

function route(info) {
  // One end is worth printing on its own: an aircraft still in the air has no
  // filed arrival yet, and "from Philadelphia" is the whole story anyway.
  const from = info.from_town || info.from;
  const to = info.to_town || info.to;
  if (from && to) return `${escapeText(from)} → ${escapeText(to)}`;
  if (from) return `${t("from")} ${escapeText(from)}`;
  if (to) return `${t("to")} ${escapeText(to)}`;
  return "";
}

function facts(info) {
  const out = [];
  if (info.altitude_m != null) out.push(`${Math.round(info.altitude_m).toLocaleString(locale())} m`);
  if (info.speed_ms != null) out.push(`${Math.round(info.speed_ms * 3.6).toLocaleString(locale())} km/h`);
  if (info.heading != null) out.push(`${t("heading")} ${Math.round(info.heading)}°`);
  // A tenth of a metre a second is level flight; below that the reading is the
  // instrument breathing, not the aircraft going anywhere.
  if (info.climb_ms != null && Math.abs(info.climb_ms) >= 1) {
    out.push(info.climb_ms > 0 ? t("climbing") : t("descending"));
  }
  if (info.distance_km != null) out.push(`${Math.round(info.distance_km)} km`);
  return out;
}

function detail(event) {
  const info = event.detail || {};
  if (event.type === "plane") {
    const place = info.seen ? "" : t("notInFrame");
    // No weather and no time of day here: the photograph beside this line
    // already says both, and said in words they would need translating twice.
    // The name is already the heading of this row when nothing better than
    // the callsign was known, and saying it twice says nothing twice.
    const name = who(info);
    const words = [name === escapeText(showText(event.label)) ? "" : name,
      route(info), ...facts(info), place].filter(Boolean).join(" · ");
    // Where to go and check. OpenSky named this aircraft but has retired its
    // own website, so the link goes to a tracker that still answers, and asks
    // it for the trace of the day we saw it rather than for a live position:
    // the aircraft has long landed, and what is worth checking is the path it
    // flew over this ridge at that hour.
    if (!info.icao24) return words;
    const day = new Date(event.t).toISOString().slice(0, 10);
    const track = `https://globe.adsbexchange.com/?icao=${encodeURIComponent(info.icao24)}&showTrace=${day}`;
    return `${words} · <a class="out" href="${track}" target="_blank" rel="noopener">${t("follow")}</a>`;
  }
  if (event.type === "bus" && info.route) {
    return `${info.headsign || info.route} · ${info.scheduled || ""} · ${info.source || ""}`.trim();
  }
  if (event.type === "fire") return showText(info.reading) || t("fireNote");
  if (info.reading) return [showText(info.context), showText(info.reading)].filter(Boolean).join(" · ");
  if (info.context) return showText(info.context);
  return "";
}

// Le modèle a-t-il lu de lui-même ce qui a été publié ? Un nom trouvé par une
// règle de rattrapage — c'est long comme un bus, donc c'est un bus — dit ce que
// la règle savait déjà, pas ce que la veille a reconnu. Seul le premier compte
// ici, et sur les 54 lectures relues jusqu'ici les 53 démenties étaient toutes
// de l'autre sorte. Les entrées antérieures à cette marque n'en portent pas et
// ne peuvent rien revendiquer : elles vont à trancher elles aussi.
function namedItself(event) {
  return (event.detail || {}).autonomous === true;
}

function render() {
  if (!list) return;
  const shown = events.filter(namedItself).filter((event) => {
    if (filter === "all") return true;
    if (filter === "vehicle") return event.type === "vehicle" || event.type === "car";
    return event.type === filter;
  });
  empty.hidden = shown.length > 0;
  const count = document.querySelector("#count");
  const right = shown.filter((event) => event.review !== "rejected").length;
  if (count) count.textContent = right ? String(right) : "";
  paintScore();
  const pages = Math.max(1, Math.ceil(shown.length / PER_PAGE));
  page = Math.min(Math.max(page, 0), pages - 1);
  const pager = document.querySelector("#pager");
  if (pager) {
    pager.hidden = shown.length <= PER_PAGE;
    const where = pager.querySelector("#pager-where");
    const first = page * PER_PAGE + 1;
    const last = Math.min((page + 1) * PER_PAGE, shown.length);
    if (where) where.textContent = t("pageOf")(first, last, shown.length);
    pager.querySelector('[data-step="-1"]').disabled = page === 0;
    pager.querySelector('[data-step="1"]').disabled = page >= pages - 1;
  }
  list.innerHTML = shown.slice(page * PER_PAGE, (page + 1) * PER_PAGE).map((event) => {
    const moment = new Date(event.t);
    const clock = moment.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Paris" });
    const day = moment.toLocaleDateString(locale(), { day: "2-digit", month: "short", year: "numeric", timeZone: "Europe/Paris" });
  // Le plan rapproche flouté plutôt que la vue d'ensemble : revoir des
    // passages reconnaissables met mal à l'aise, et republier indéfiniment des
    // Les deux images : la vue d'ensemble dit où, la découpe dit quoi, et il
    // faut les deux pour juger. Elles sont nettes ici, et c'est voulu — un car
    // dont on ne lit plus le flanc n'est plus jugeable. Le floutage, lui, est
    // posé à l'antenne, où des passages sont rejoués devant des gens qui ne
    // l'ont pas demandé.
    const shot = event.thumb || event.closeup;
    const picture = shot
      ? `<img src="${escapeHtml(shot)}" alt="" loading="lazy" decoding="async">`
      : `<span class="placeholder"></span>`;
    const info = event.detail || {};
    const people = Number(info.persons || 0);
    const title = people > 1 ? `${showText(event.label)} (${people})` : showText(event.label);
    // Only for aircraft. The rest of this log is a time, a word and a picture
    // on purpose; an aircraft is the one thing here that cannot be checked by
    // looking, so it carries its numbers and the place they came from.
    const extra = event.type === "plane" ? `<span class="sub">${detail(event)}</span>` : "";
    const place = t("places")[info.surface || event.zone] || "";
    // Une lecture que vous avez dite fausse reste ici, barrée. La retirer
    // ferait une belle page et un mauvais registre : on ne peut pas viser le
    // zéro faute en effaçant les fautes, et c'est de celles-là qu'on apprend.
    const wrong = event.review === "rejected" ? ' class="wrong"' : "";
    // Et ce que c'était. Une ligne barrée dit qu'on s'est trompé sans dire sur
    // quoi, ce qui est la seule chose que le lecteur veut savoir et la seule
    // que nous ayons apprise de la soirée.
    const truth = info.truth ? `<span class="sub">${escapeHtml(info.truth)}</span>` : "";
    return `<tr${wrong}><td class="when"><time>${clock}</time><span>${day}</span></td>`
      + `<td class="event">${escapeHtml(title)}${extra}${truth}</td>`
      + `<td class="place">${escapeHtml(place)}</td>`
      + `<td class="shot">${picture}</td></tr>`;
  }).join("");
  paintDoubt();
}

// Combien il faut contrôler, sans une seule faute, pour pouvoir dire 95 %.
//
// Sans aucune faute, la borne basse exacte du taux vaut 0,05^(1/n) : c'est le
// taux le plus mauvais qui aurait tout de même une chance sur vingt de passer n
// tirages sans se faire prendre. Elle atteint 0,95 quand n dépasse
// ln(0,05)/ln(0,95) ≈ 58,4, donc à cinquante-neuf. Moins, et on n'affirme
// rien ; une faute, et il en faut bien davantage.
const CLEAN_RUN = 59;

// Un ordre au hasard mais toujours le même, tiré de l'identifiant. Trier par
// date mettrait tout le contrôle sur une seule journée, et laisser choisir
// mesurerait ce qu'on aime regarder plutôt que ce que la veille sait faire.
function scramble(id) {
  let hash = 2166136261;
  for (const letter of String(id)) {
    hash ^= letter.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967296;
}

// Ce qu'on a le droit d'affirmer, à 95 % de confiance. Douze justes sur douze
// ne veulent pas dire cent pour cent : ils veulent dire au moins
// soixante-dix-huit, et c'est ce nombre-là qu'il faut écrire.
function sureAtLeast(right, read) {
  if (!read) return 0;
  // Sans faute, la borne exacte tient en une ligne, et c'est le cas qui décide
  // de la publication. Wilson est légèrement optimiste tout près de cent pour
  // cent, ce qui est exactement l'endroit où on ne veut pas l'être.
  if (right === read) return Math.pow(0.05, 1 / read);
  // Sinon la borne basse de Wilson, unilatérale.
  const z = 1.645;
  const seen = right / read;
  const weight = 1 + (z * z) / read;
  const middle = (seen + (z * z) / (2 * read)) / weight;
  const spread = (z / weight) * Math.sqrt((seen * (1 - seen)) / read + (z * z) / (4 * read * read));
  return Math.max(0, middle - spread);
}

// Le tirage de contrôle : des publications que personne n'a encore lues, prises
// dans l'ordre du brassage. Une douzaine à la fois, parce qu'une page de
// soixante cartes ne se juge pas d'un trait.
function paintControl() {
  const box = document.querySelector("#control-list");
  const block = document.querySelector("#control");
  if (!box || !block) return;
  const published = events.filter((event) => namedItself(event)
    && !(event.detail || {}).simulation);
  const waiting = published.filter((event) => !event.review)
    .sort((one, other) => scramble(one.id) - scramble(other.id))
    .slice(0, 12);
  block.hidden = waiting.length === 0;
  document.querySelector("#control-title").textContent = t("control");
  document.querySelector("#control-why").textContent = t("controlWhy");
  box.innerHTML = waiting.map(card).join("");
}

let doubtPage = 0;

// Tout ce que la veille a vu bouger sans le reconnaître elle-même : une carte
// par passage, la photo en grand et la supposition écrite dessous. Les boutons
// ouvrent un ticket qui corrige l'entrée et dépose une ligne dans
// data/reviewed.jsonl ; c'est de là que viendra le prochain réglage, sinon un
// verdict ne serait qu'un compteur de plus.
function paintDoubt() {
  const box = document.querySelector("#doubt-list");
  if (!box) return;
  const waiting = events.filter((event) => !namedItself(event)
    && !(event.detail || {}).simulation);
  const why = document.querySelector("#doubt-why");
  if (why) why.textContent = t("doubtWhy");
  const tally = document.querySelector("#doubt-count");
  if (tally) tally.textContent = t("doubtCount")(waiting.length);
  const nothing = document.querySelector("#doubt-empty");
  if (nothing) nothing.hidden = waiting.length > 0;

  const pages = Math.max(1, Math.ceil(waiting.length / PER_PAGE));
  doubtPage = Math.min(Math.max(doubtPage, 0), pages - 1);
  const pager = document.querySelector("#doubt-pager");
  if (pager) {
    pager.hidden = waiting.length <= PER_PAGE;
    const where = pager.querySelector("#doubt-where");
    const first = doubtPage * PER_PAGE + 1;
    const last = Math.min((doubtPage + 1) * PER_PAGE, waiting.length);
    if (where) where.textContent = t("pageOf")(first, last, waiting.length);
    pager.querySelector('[data-step="-1"]').disabled = doubtPage === 0;
    pager.querySelector('[data-step="1"]').disabled = doubtPage >= pages - 1;
  }

  document.querySelector("#doubt-list-title").textContent = t("doubtList");
  box.innerHTML = waiting.slice(doubtPage * PER_PAGE, (doubtPage + 1) * PER_PAGE)
    .map(card).join("");
  paintControl();
}

// La découpe que le modèle a vue, gardée à la résolution de la source. La
// vignette fait 480 pixels de large pour une image de 1920 : une voiture au
// rond-point y tient sur trente pixels, assez pour voir que quelque chose est
// passé, pas pour dire si c'est un fourgon ou un break. La découpe en a quatre
// fois plus. Elle vient à côté du cadre entier et non à sa place : agrandie
// seule, elle ne dit plus où l'on regarde, et sans le lieu on ne juge rien.
function bigger(event) {
  return event.closeup ? ` data-big="${escapeHtml(event.closeup)}"` : "";
}

// Une carte : la photo en grand, l'heure, la supposition et les mots à choisir.
// La même pour le contrôle et pour ce qui attend un avis, sans quoi les deux
// finiraient par ne plus poser tout à fait la même question.
function card(event) {
  const moment = new Date(event.t);
  const clock = moment.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Paris" });
  const day = moment.toLocaleDateString(locale(), { day: "2-digit", month: "short", timeZone: "Europe/Paris" });
  // Le plan rapproche flouté plutôt que la vue d'ensemble : revoir des
  // passages reconnaissables met mal à l'aise, et republier indéfiniment des
  // Les deux images : la vue d'ensemble dit où, la découpe dit quoi, et il
  // faut les deux pour juger. Elles sont nettes ici, et c'est voulu — un car
  // dont on ne lit plus le flanc n'est plus jugeable. Le floutage, lui, est
  // posé à l'antenne, où des passages sont rejoués devant des gens qui ne
  // l'ont pas demandé.
  const shot = event.thumb || event.closeup;
  const picture = shot
    ? `<img src="${escapeHtml(shot)}" alt="" loading="lazy" decoding="async">`
    : `<span class="placeholder"></span>`;
  const info = event.detail || {};
  const place = t("places")[info.surface || event.zone] || "";
  // Ce qui a déjà été tranché reste, avec son verdict visible : revenir sur un
  // avis doit être possible, et une carte qui disparaît une fois jugée
  // enlèverait le moyen de se corriger.
  const done = event.review ? ` judged ${event.review}` : "";
  // Une tache écartée porte la marque de son refus : la question qu'on lui pose
  // n'est pas la même. Sur une publication on demande si le nom est juste ; sur
  // un refus, s'il y avait quelque chose que la veille a manqué.
  const missed = event.type === "missed" ? " missed" : "";
  return `<figure class="card${missed}${done}">${picture}`
    + `<figcaption><span class="when">${clock} · ${day}</span>`
    + `<span class="guess">${escapeHtml(showText(event.label))}</span>`
    + `<span class="place">${escapeHtml(place)}</span>`
    + `${reviewControls(event, { naming: true })}</figcaption></figure>`;
}

// The order the bars are stacked in, bottom first, and the order the legend
// reads. Fixed rather than taken from the data, so a quiet day does not
// reshuffle the colours and make two charts impossible to compare.
const KINDS = ["vehicle", "person", "bus", "fire", "plane", "other"];

function kindOf(event) {
  if (event.type === "car") return "vehicle";
  return KINDS.includes(event.type) ? event.type : "other";
}

// Paris time, because that is the clock the history is written in and the one
// the hillside lives by. Reading the hour off the browser would put a visitor
// in California nine hours out and make the busiest hour of the day midnight.
function parisParts(stamp) {
  const bits = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Paris", weekday: "short", hour: "2-digit", hour12: false,
    year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(stamp));
  const get = (kind) => bits.find((part) => part.type === kind)?.value || "";
  const days = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
  return {
    hour: Number(get("hour")) % 24,
    day: days[get("weekday")] ?? 0,
    date: `${get("year")}-${get("month")}-${get("day")}`,
  };
}

function paintFigures() {
  const hourBox = document.querySelector("#by-hour");
  const dayBox = document.querySelector("#by-day");
  const legend = document.querySelector("#figures-legend");
  const span = document.querySelector("#figures-span");
  if (!hourBox || !dayBox || !legend || !span) return;
  // A drawn fire is not a fire that happened. These figures are meant to say
  // what goes past this camera at which hour, and a simulation went past
  // nothing: the two on file were the only entries in the "fire" column and
  // gave it 0.7 % of the whole. Et les couleurs de ces barres sont les noms :
  // un nom dont la veille n'est pas sûre fait une barre fausse, d'où les mêmes
  // passages que l'historique, ceux que le modèle a lus lui-même.
  const seen = events.filter((event) => namedItself(event)
    && !(event.detail || {}).simulation && event.review !== "rejected");
  if (!seen.length) {
    span.textContent = t("figuresEmpty");
    hourBox.innerHTML = dayBox.innerHTML = legend.innerHTML = "";
    return;
  }
  const hours = Array.from({ length: 24 }, () => ({}));
  const days = Array.from({ length: 7 }, () => ({}));
  const whole = {};
  const dates = new Set();
  for (const event of seen) {
    const kind = kindOf(event);
    const when = parisParts(event.t);
    dates.add(when.date);
    hours[when.hour][kind] = (hours[when.hour][kind] || 0) + 1;
    days[when.day][kind] = (days[when.day][kind] || 0) + 1;
    whole[kind] = (whole[kind] || 0) + 1;
  }
  span.textContent = t("figuresSpan")(dates.size, seen.length);
  legend.innerHTML = KINDS.filter((kind) => whole[kind]).map((kind) =>
    `<span class="key"><i style="background:var(--cat-${kind})"></i>${escapeHtml(t("kinds")[kind])}`
    + ` <b>${share(whole[kind], seen.length)}</b></span>`).join("");
  hourBox.innerHTML = bars(hours, seen.length, (index) => String(index).padStart(2, "0"));
  dayBox.innerHTML = bars(days, seen.length, (index) => t("weekdays")[index]);
}

function share(part, all) {
  if (!all) return "0 %";
  const value = (part / all) * 100;
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} %`;
}

function bars(buckets, all, label) {
  // Heights are read against the busiest bucket, so the tallest bar fills the
  // panel whatever the totals are; the number printed on it is the share of
  // everything, which is the figure that means something on its own.
  const totals = buckets.map((bucket) => Object.values(bucket).reduce((sum, n) => sum + n, 0));
  const peak = Math.max(1, ...totals);
  return buckets.map((bucket, index) => {
    const total = totals[index];
    const parts = KINDS.filter((kind) => bucket[kind]).map((kind) =>
      `<i style="flex:${bucket[kind]};background:var(--cat-${kind})"></i>`).join("");
    const told = KINDS.filter((kind) => bucket[kind])
      .map((kind) => `${t("kinds")[kind]} ${bucket[kind]}`).join(" · ");
    return `<div class="bar" title="${escapeHtml(`${label(index)} — ${share(total, all)}${told ? ` · ${told}` : ""}`)}">`
      + `<b class="val">${total ? share(total, all) : ""}</b>`
      + `<span class="col" style="height:${(total / peak) * 100}%">${parts}</span>`
      + `<span class="tick">${escapeHtml(label(index))}</span></div>`;
  }).join("");
}

const REVIEW_CLASSES = [
  ["voiture", "carWord", "Voiture"],
  ["camion", "vanWord", "Camion"],
  ["bus", "busWord", "Bus"],
  ["pieton", "walkerWord", "Piéton"],
  ["velo", "cycleWord", "Vélo"],
  ["tracteur", "tractorWord", "Tracteur"],
];

// La question posée à trancher n'est pas « est-ce juste ? » mais « qu'y
// avait-il ? ». Un simple démenti laisse l'entrée sans nom et n'apprend rien au
// modèle : le mot juste, lui, part dans data/reviewed.jsonl avec la mesure de
// la tache, et c'est de ce couple que sortira le prochain réglage.
function reviewControls(event, { naming = false } = {}) {
  // Sauf pour ce qui vole : les cinq mots sont ceux du sol, et aucun ne
  // convient à un avion. La règle est ici plutôt que chez l'appelant, pour
  // qu'aucune page ne puisse la manquer.
  const ground = event.type !== "plane";
  if (ground && (event.type === "motion" || naming)) {
    const correction = (event.detail || {}).correction;
    const rejected = event.review === "rejected" ? " on" : "";
    // Le mot que la machine a lu est marqué. Les neuf boutons se ressemblaient
    // tous, et rien ne disait que cliquer celui-là voulait dire « juste » :
    // « Est juste ! mais je sais pas comment l'indiquer ». La question posée
    // reste « qu'y avait-il ? », parce qu'un oui sans mot n'apprend rien ; il
    // suffit qu'on voie lequel était la réponse de la machine.
    const read = event.label;
    const choices = REVIEW_CLASSES.map(([classe, word, label]) =>
      `<a class="yes${correction === label ? " on" : ""}${label === read ? " lu" : ""}" href="${reviewUrl(event, "accepted", "valide", classe)}">${escapeHtml(t(word))}</a>`).join("");
    // Sur une publication, démentir veut dire « ce n'était pas cela ». Sur une
    // tache écartée, cela veut dire « il n'y avait rien », donc que le refus
    // avait raison. Le même bouton, deux phrases opposées : il faut les écrire.
    const deny = event.type === "missed" ? "nothing" : "wrong";
    return `<p class="verdict">${choices}<a class="no${rejected}" href="${reviewUrl(event, "rejected", "rejete")}">${escapeHtml(t(deny))}</a></p>`;
  }
  const accepted = event.review === "accepted" ? " on" : "";
  const rejected = event.review === "rejected" ? " on" : "";
  return `<p class="verdict"><a class="yes${accepted}" href="${reviewUrl(event, "accepted", "valide")}">${escapeHtml(t("right"))}</a><a class="no${rejected}" href="${reviewUrl(event, "rejected", "rejete")}">${escapeHtml(t("wrong"))}</a></p>`;
}

function reviewUrl(event, verdict, label, classe) {
  const title = `revue ${event.id}`;
  const body = `event_id: ${event.id}\nverdict: ${verdict}\nlecture: ${event.label}\n${classe ? `classe: ${classe}\n` : ""}`;
  return `https://github.com/Medialoco/ventoux-watch/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}&labels=${label}`;
}

// Colours are written after the word and spelt to agree with it, so English
// needs both spellings back.
const TINTS = {
  blanche: "white", blanc: "white",
  noire: "black", noir: "black",
  grise: "grey", gris: "grey",
  rouge: "red", orange: "orange", jaune: "yellow",
  verte: "green", vert: "green",
  bleue: "blue", bleu: "blue",
  marron: "brown",
};

function showText(value) {
  if (!value || lang === "fr") return value || "";
  if (LABELS[value]) return LABELS[value];
  const parts = value.split(" ");
  const tint = TINTS[parts[parts.length - 1]];
  if (tint) {
    const rest = showText(parts.slice(0, -1).join(" "));
    return `${tint.charAt(0).toUpperCase()}${tint.slice(1)} ${rest.toLowerCase()}`;
  }
  return value;
}

function paintScore() {
  // Le but est un pipeline qui ne se trompe jamais, et cela se prouve par un
  // taux plutôt que par une sélection. Le compte est tenu sur ce qui a été
  // relu : une publication que personne n'a regardée n'est ni juste ni fausse.
  const box = document.querySelector("#score");
  if (!box) return;
  // Le compte porte sur ce que le site publie, c'est-à-dire sur les lectures
  // que le modèle a faites seul. Y mêler celles qui attendent un avis
  // mesurerait la file d'attente plutôt que la veille.
  const real = events.filter((event) => namedItself(event)
    && !(event.detail || {}).simulation);
  const read = real.filter((event) => event.review);
  // Une entrée corrigée à la main porte aujourd'hui le bon mot, mais elle
  // était fausse quand elle a été publiée, et c'est cela qu'on compte. Sans
  // cette ligne le score dirait 53 justes sur 54 en ne montrant que le travail
  // de correction : il flatterait exactement la chose qu'il est censé juger.
  const right = read.filter((event) => event.review === "accepted"
    && !(event.detail || {}).correction);
  box.textContent = t("scoreLine")(real.length, read.length, right.length);
  box.hidden = read.length === 0;

  // Ce qu'on a le droit d'affirmer, qui n'est pas ce qu'on a compté. Douze
  // justes sur douze ne font pas cent pour cent : ils font au moins
  // soixante-quatorze, et c'est ce nombre-là qui doit être écrit.
  const claim = document.querySelector("#claim");
  if (!claim) return;
  claim.hidden = read.length === 0;
  const floor = Math.floor(sureAtLeast(right.length, read.length) * 100);
  const clean = read.length === right.length;
  claim.textContent = t("claimLine")(floor, clean ? Math.max(0, CLEAN_RUN - read.length) : 0);
}

function paintCounts() {
  if (!counts) return;
  const seen = document.querySelector("#seen");
  if (!seen) return;
  seen.textContent = String(counts.seen || 0);
  // The breakdown belongs beside the history it describes. In the top bar it
  // was a second line under the total, and the bar has no second line to give.
  const tally = document.querySelector("#tally");
  if (tally) tally.textContent = t("namedLine")(counts.named || 0, counts.habits || 0);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

async function load() {
  const response = await fetch("data/events.json", { cache: "no-store" });
  const payload = await response.json();
  events = payload.events || [];
  const stamp = document.getElementById("version");
  if (stamp && payload.version) stamp.textContent = `v${payload.version}`;
  render();
  paintFigures();
  try {
    const learning = await fetch("data/learning.json", { cache: "no-store" });
    if (learning.ok) {
      counts = await learning.json();
      paintCounts();
    }
  } catch (_) {
    /* Le compteur apparaît quand le Pi a commencé à apprendre. */
  }
}

// Le cône n'est pas déclaré, il est mesuré. build_scene.py déplace le cap, le
// site, le champ, la hauteur et jusqu'à la position de la caméra tant que les
// dix-neuf repères OSM ne tombent pas là où on les voit dans l'image, et écrit
// le résultat dans config/scene.json. Ces trois nombres étaient écrits à la
// main ici : 140° de cap, 90° de champ, 600 m de portée, quand le calage dit
// 126,7°, 78,8° et 2500 m. Le cône montré pointait treize degrés à côté et
// s'arrêtait au quart de ce que la caméra atteint.
//
// L'écart résiduel du calage vaut 0,0136 en largeur d'image. Multiplié par le
// champ, 0,0136 × 78,755° ≈ 1,1° : c'est la précision du cap. Le calcul qui
// mène à camera:direction=127 est écrit dans scripts/build_scene.py.
const AIM_FALLBACK = { lat: 44.1833492, lon: 5.2620281, yaw: 126.713, hfov: 78.755, reach: 2500 };
let aim = AIM_FALLBACK;

function offset(lat, lon, bearing, meters) {
  const rad = Math.PI / 180;
  const distance = meters / 6371000;
  const br = bearing * rad;
  const lat1 = lat * rad;
  const lon1 = lon * rad;
  const lat2 = Math.asin(Math.sin(lat1) * Math.cos(distance) + Math.cos(lat1) * Math.sin(distance) * Math.cos(br));
  const lon2 = lon1 + Math.atan2(Math.sin(br) * Math.sin(distance) * Math.cos(lat1), Math.cos(distance) - Math.sin(lat1) * Math.sin(lat2));
  return [lat2 / rad, lon2 / rad];
}

function viewWedge() {
  const points = [[aim.lat, aim.lon]];
  const start = aim.yaw - aim.hfov / 2;
  for (let step = 0; step <= 28; step += 1) {
    points.push(offset(aim.lat, aim.lon, start + (aim.hfov * step) / 28, aim.reach));
  }
  return points;
}

// La portée du calage est de deux kilomètres et demi, mais ce qui a vraiment
// été reconnu tient entre 106 et 830 m : les trois niveaux cadrent sur cette
// bande-là, pas sur le bout du cône.
function zoomLevels() {
  return [
    { zoom: 18, along: 0 },
    { zoom: 16, along: aim.reach * 0.08 },
    { zoom: 14, along: aim.reach * 0.16 },
  ];
}

const map = L.map("map", {
  scrollWheelZoom: false,
  zoomControl: false,
  doubleClickZoom: false,
  boxZoom: false,
  keyboard: false,
  attributionControl: false,
});
L.control.attribution({ prefix: false }).addTo(map);
L.tileLayer("https://data.geopf.fr/wmts?LAYER=ORTHOIMAGERY.ORTHOPHOTOS&FORMAT=image/jpeg&SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}", {
  maxZoom: 19,
  attribution: "© IGN",
}).addTo(map);
const wedge = L.polygon(viewWedge(), {
  color: "#c4b094",
  weight: 2,
  fillColor: "#e8dcc4",
  fillOpacity: 0.28,
}).addTo(map);
const axis = L.polyline([
  [aim.lat, aim.lon],
  offset(aim.lat, aim.lon, aim.yaw, aim.reach),
], { color: "#c4b094", weight: 2, dashArray: "4 6" }).addTo(map);
const cameraMark = L.circleMarker([aim.lat, aim.lon], {
  radius: 6,
  color: "#f4f1ea",
  weight: 2,
  fillColor: "#243f34",
  fillOpacity: 1,
}).addTo(map);

function showZoom(index) {
  const level = zoomLevels()[index];
  map.setView(offset(aim.lat, aim.lon, aim.yaw, level.along), level.zoom);
  document.querySelectorAll(".zooms button").forEach((button) => {
    button.classList.toggle("on", Number(button.dataset.zoom) === index);
  });
}

document.querySelectorAll(".zooms button").forEach((button) => {
  button.addEventListener("click", () => showZoom(Number(button.dataset.zoom)));
});
showZoom(1);
function sizeMap() {
  map.invalidateSize();
}
requestAnimationFrame(sizeMap);
if (window.IntersectionObserver) {
  const cadre = document.querySelector("#camera");
  if (cadre) {
    new IntersectionObserver((vues) => {
      if (vues.some((vue) => vue.isIntersecting)) sizeMap();
    }, { threshold: 0.05 }).observe(cadre);
  }
}

async function loadAim() {
  // Relu à chaque visite plutôt que recopié dans ce fichier : le jour où la
  // caméra passera sur le toit du chalet, le calage changera et la carte doit
  // suivre sans qu'on y pense.
  try {
    const response = await fetch("data/scene.json", { cache: "no-store" });
    if (!response.ok) return;
    const pose = (await response.json()).pose || {};
    if (!pose.yaw || !pose.hfov) return;
    aim = {
      lat: pose.lat ?? aim.lat,
      lon: pose.lon ?? aim.lon,
      yaw: pose.yaw,
      hfov: pose.hfov,
      reach: pose.reach_m || aim.reach,
      rms: pose.rms || 0,
    };
  } catch (_) {
    /* Le cône reste sur le dernier calage connu. */
  }
  wedge.setLatLngs(viewWedge());
  axis.setLatLngs([[aim.lat, aim.lon], offset(aim.lat, aim.lon, aim.yaw, aim.reach)]);
  cameraMark.setLatLng([aim.lat, aim.lon]);
  showZoom(1);
  paintAim();
}

function paintAim() {
  const label = document.querySelector('[data-i18n="cameraText"]');
  if (!label) return;
  const spread = aim.rms ? ` ± ${(aim.rms * aim.hfov).toFixed(1)}°` : "";
  label.textContent = `${t("cameraFixed")} ${aim.yaw.toFixed(1)}°${spread} · ${t("cameraField")} ${aim.hfov.toFixed(1)}°`;
  label.removeAttribute("data-i18n");
}

function paintCamera() {
  cameraMark.unbindTooltip();
  cameraMark.bindTooltip(t("camera"), { permanent: true, direction: "top", offset: [0, -8] });
}

let sequenceFrames = [];
let sequenceIndex = 0;

const FOOT = 14;

function followSections() {
  /* Put a section on screen whole, and underline the one being read.

     Every section on this page but the log is shorter than a screenful, so
     landing on one has no business showing its first line and leaving its last
     below the fold. Clicking a heading centres the section in the room left
     under the bar; only the log, which is the whole history and has no bottom
     worth reaching, is aligned by its top.

     The underline follows whichever section fills most of the screen rather
     than whichever one last crossed a line, because once a section is centred
     its heading sits below that line and the previous one would keep winning. */
  const links = [...document.querySelectorAll(".onpage a")];
  const parts = links
    .map((link) => {
      const href = link.getAttribute("href") || "";
      return href.startsWith("#") ? document.querySelector(href) : null;
    })
    .filter(Boolean);
  if (!parts.length) return;
  const top = document.querySelector(".top");
  const waterline = () => (top?.offsetHeight || 78) + 8;

  const reveal = (part) => {
    const line = waterline();
    const room = window.innerHeight - line;
    const box = part.getBoundingClientRect();
    let y = window.scrollY + box.top - line;
    if (box.height < room) {
      // Settle on the foot of the section, not its head. What tells a reader
      // that a section is finished is seeing where it stops; landing on the
      // title leaves them to guess how much is still below.
      y = window.scrollY + box.bottom - window.innerHeight + FOOT;
      y = Math.min(y, window.scrollY + box.top - line);
    }
    window.scrollTo({ top: Math.max(Math.round(y), 0), behavior: "smooth" });
  };

  for (const link of links) {
    link.addEventListener("click", (hit) => {
      const href = link.getAttribute("href") || "";
      if (!href.startsWith("#")) return;
      const part = document.querySelector(href);
      if (!part) return;
      hit.preventDefault();
      reveal(part);
      history.replaceState(null, "", href);
    });
  }

  const mark = () => {
    // Anything past the first screenful means the visit has started.
    const line = waterline();
    // Whichever section the waterline itself falls in. Counting visible pixels
    // instead handed the underline to the history the moment any of it showed,
    // because it is forty thousand pixels long and wins any such contest.
    let here = parts.find((part) => {
      const box = part.getBoundingClientRect();
      return box.top <= line && box.bottom > line;
    }) || parts.find((part) => part.getBoundingClientRect().top > line) || parts[0];
    if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) here = parts[parts.length - 1];
    for (const link of links) {
      const on = link.getAttribute("href") === `#${here.id}`;
      if (on) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    }
  };
  let waiting = false;
  addEventListener("scroll", () => {
    // Once per frame at most. Scrolling fires far faster than the page repaints.
    if (waiting) return;
    waiting = true;
    requestAnimationFrame(() => { waiting = false; mark(); });
  }, { passive: true });
  addEventListener("resize", mark);
  mark();
}

applyLang();
setInterval(tick, 1000);
loadWeather();
setInterval(loadWeather, 600000);
loadView();
setInterval(loadView, 60000);
loadAim();

function paintSequence() {
  const frame = sequenceFrames[sequenceIndex];
  if (!frame || !document.querySelector("#seq-img")) return;
  document.querySelector("#seq-img").src = frame.thumb;
  document.querySelector("#seq-frame").href = `https://www.mapillary.com/app/?pKey=${encodeURIComponent(frame.id)}&focus=photo`;
  document.querySelector("#seq-count").textContent = `${sequenceIndex + 1} / ${sequenceFrames.length}`;
  const date = new Date(frame.captured_at).toLocaleDateString(locale(), { month: "long", year: "numeric" });
  document.querySelector("#sequence-meta").textContent = `Mapillary · ${date}`;
}

function stepSequence(delta) {
  if (!sequenceFrames.length) return;
  sequenceIndex = (sequenceIndex + delta + sequenceFrames.length) % sequenceFrames.length;
  paintSequence();
}

async function mly(pathname, params) {
  const url = new URL(pathname ? `https://graph.mapillary.com/${pathname}` : "https://graph.mapillary.com/");
  url.searchParams.set("access_token", "MLY|26158465847163536|0186af2cabb143cd46cccc023e7f0d81");
  Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
  const response = await fetch(url);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function loadSequence() {
  if (!document.querySelector("#sequence")) return;
  const pad = 0.02;
  const bbox = [CAMERA.lon - pad, CAMERA.lat - pad, CAMERA.lon + pad, CAMERA.lat + pad].join(",");
  const nearby = await mly("images", { fields: "id,computed_geometry,captured_at", bbox, limit: "200" });
  const near = (nearby.data || []).map((img) => {
    const coords = (img.computed_geometry || {}).coordinates;
    if (!coords || !img.captured_at) return null;
    return { id: img.id, captured_at: img.captured_at, lat: coords[1], lon: coords[0], dist: km(CAMERA, { lat: coords[1], lon: coords[0] }) };
  }).filter((img) => img && img.dist < 0.8);
  if (!near.length) return;
  const newest = Math.max(...near.map((img) => img.captured_at));
  let recent = near.filter((img) => newest - img.captured_at < 3 * 60 * 60 * 1000);
  recent.sort((a, b) => a.captured_at - b.captured_at);
  if (recent.length > 6) {
    const step = (recent.length - 1) / 5;
    recent = [0, 1, 2, 3, 4, 5].map((index) => recent[Math.round(index * step)]);
  }
  const details = await mly("", { fields: "id,thumb_1024_url,captured_at", ids: recent.map((img) => img.id).join(",") });
  sequenceFrames = recent.map((img) => {
    const shot = details[img.id];
    if (!shot || !shot.thumb_1024_url) return null;
    return { ...img, thumb: shot.thumb_1024_url, captured_at: shot.captured_at || img.captured_at };
  }).filter(Boolean);
  if (!sequenceFrames.length) return;
  const here = sequenceFrames.slice().sort((a, b) => a.dist - b.dist)[0];
  document.querySelector("#sequence-osm").href = `https://www.openstreetmap.org/?mlat=${here.lat}&mlon=${here.lon}#map=18/${here.lat}/${here.lon}`;
  sequenceIndex = 0;
  document.querySelector("#sequence").hidden = false;
  paintSequence();
}

document.querySelector("#seq-prev")?.addEventListener("click", () => stepSequence(-1));
document.querySelector("#seq-next")?.addEventListener("click", () => stepSequence(1));

load();
setInterval(load, 60000);
loadSequence();
followSections();
