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
    pipelineLead: "1 frame/s from the webcam. MOG2 on a frame scaled to 640 px. A compact blob held 3 frames is cropped. YOLO11s, ONNX, names the crop. The rectangle goes back on the original frame. The frame is encoded to YouTube. When the Mont Serein playlist closes, that frame is the Cannes webcam.",
    numbers: "On the stream",
    numbersLead: "One set piece at a time. A turn is taken only when the stage is free at the instant it starts; otherwise that whole turn is skipped. Periods are prime numbers. At night every period on that stage except the bear’s is divided by 3, and the start delay is divided by the same factor. Pixel, grey and wave are a separate draw, not on that stage. The bear keeps his own pace. Each row below is what is drawn, with its period, its duration and its gate, measured from the code that is running.",
    effectColName: "Name",
    effectColWhat: "What happens",
    effectDay: "Day",
    effectWire: "Wire",
    effectBubbles: "Bubbles",
    effectFish: "Fish",
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
    effectReplay: "Replay",
    effectMeet: "Meeting",
    effectVersion: "Version",
    effectDeploy: "Deployed",
    effectFriend: "Friend",
    effectDijon: "Dijon",
    musicTitle: "Dogmazic",
    musicLead: "Dogmazic is a free-music library. The artists keep the rights and choose a Creative Commons licence, so a stream can play the work in public as long as it names the author, the title, the licence and a place to find the file. Fourteen hours and thirteen minutes turn here, one hundred and fifty-eight tracks, all from that library. Four hours of that are the album Mont Serein 002, written for this project. The playlist is public.",
    rebuild: "Rebuilt",
    rebuildLead: "ffmpeg reads the webcam at 1 frame/s. MOG2 runs at 640 px. A compact blob held 3 frames is cropped. YOLO11s, ONNX, names the crop. The rectangle is drawn on the original frame. Overlays sit in the letterbox. The frame is encoded to YouTube.",
    watchPi: "4 cores, Los Angeles. It reads the frame, keeps the archive, mixes the music, draws the overlays, and pushes the frame. Temperature and load stay on its card.",
    watchMotion: "MOG2. Frame scaled to 640 px. A change over 35% of the frame is treated as light and dropped. The red beacon on the summit is masked.",
    watchClass: "YOLO11s, ONNX, on the crop only. Car, person, bicycle, truck, bus.",
    watchEffectsTitle: "Effects",
    watchEffects: "Drawn on the frame. The table below gives the period, the duration and the gate of each one.",
    watchMusicTitle: "Music",
    watchMusic: "The Pi selects the track and ducks it under a voice. Under the picture: previous cover, current track, next two, artist, title, licence, equaliser.",
    watchOut: "The frame is encoded and sent to YouTube.",
    listen: "Listen on Dogmazic",
    radio: "Audio stream",
    radioOn: "Listening",
    chipFps: "1 frame / s",
    story: "The watch",
    heroLead: "A Raspberry Pi 5 in Los Angeles reads the Mont Serein webcam one frame a second, finds motion with OpenCV, names what moved with YOLO, and rebuilds the picture as a YouTube stream. When that playlist closes, the frame is the Cannes webcam, on Boulevard du Midi. The watch is the work. The stream is the show.",
    heroMachine: "Four cores on a desk, nine thousand kilometres from the pass. The Pi keeps the archive, mixes the music, draws the overlays and pushes the whole frame to YouTube in a continuous loop.",
    heroSee: "Vehicles and pedestrians are further along. Wildlife, birds, aircraft matched with OpenSky, and pets are where the work is going now. The model is trying to see everything that moves, and to name it correctly.",
    heroMusic: "Fourteen hours and thirteen minutes of free music play around the clock, all of it from Dogmazic. Four hours of that are the album Mont Serein 002, written for this project. One hundred and fifty-eight tracks sit in a public playlist you can open in a click.",
    stage: "On the stream",
    stageLead: "Pixel, grey and wave share one draw. A filmed flyover of the relief takes the window when the road is empty. The other rows are the set pieces.",
    stillConsole: "While a track plays, a console spans the width under the picture: the cover just finished, the one playing, and the next two. With the playing track sit the artist, the title, the licence and the domain of the file. An equaliser follows the music. The release number stays for the session. The clock is the image counter, not the bytes waiting in the encoder, so the credit matches what is heard.",
    stillDay: "Left card, America/Los_Angeles. Right card, Europe/Paris, Beaumont-du-Ventoux. The calendars sit about nine hours apart, so past midnight in France the two dates differ. Three digits under each card: the integer part of that day’s ratio times 100. No motion reads 000. Under the digits, in small grey, catches over motions. A published class counts as soon as it is named, on both calendars, on each side’s current date: vehicle, car, truck, bus, person, cycle, plane, aircraft, animal. The higher ratio is green. A tie stays white. The green cheer waits for confidence 0.60. At one side’s midnight the line NEW DAY IN LOS ANGELES or NEW DAY IN BEAUMONT holds for 8 s, and only that reel returns to 000.",
    stillFil: "A wire joins the two cards for the whole session. It is not on the stage clock. It leaves the lower corner of each card, drops through the black band, passes a pulley of radius 7 px at the 1600 px reference, and crosses 28 px under the camera window. Rest sag is 6 px. The cards drift against each other, and the wire sags and tightens with that drift.",
    stillBulles: "Always on, in the black bands, eight bubbles a side. A bubble is a pale ring. Its radius grows from 5 px to 10 px at the 1600 px reference as it climbs. The slowest rise takes 8.9 s, the fastest 4.9 s. Lateral drift is 11 px. Peak opacity is 0.55. They are drawn first, so the cards, the puppets and the camera window pass in front.",
    stillPoissons: "Three fish cross those bands. Periods 71 s, 97 s and 127 s, prime to each other. Each fish is drawn only for the first 0.45 of its period, so the bands are often empty. One turn it climbs, the next it dives, and it changes band each turn. Length 58 px at the 1600 px reference, opacity 0.9. Pixels that would land on the camera window are wiped before the mix. If the window already touches the frame edge, the fish stay off.",
    stillPixel: "Every 420 s one treatment is drawn from five slots, two of them empty, so the photograph often stays as it is. The slot is chosen from the block index alone, so a restart resumes the same treatment. Pixel holds 20 s and fades over 3.5 s at each end. The frame is reduced to 26 columns and enlarged nearest-neighbour. Pixel, grey and wave never run together. They stay off for 4 s after a named subject is on screen.",
    stillGris: "Same draw as pixel, same 20 s, same 3.5 s fade. Colour is mixed toward perceived luminance: a blue sky and a green slope of the same arithmetic mean do not have the same lightness, and the mix follows that lightness. At full strength the slope is grey, then the colour returns.",
    stillOndule: "Same draw as pixel. Twenty-eight horizontal bands slide sideways by up to 3% of the width. The Pi shifts whole rows. A remap of every pixel is not used: it would rebuild two maps of two million floats on every frame while the Pi is encoding.",
    stillFly: "Gate: 300 s with nothing named, and no replay up. The relief takes the camera window and holds still, on the webcam’s own viewpoint. Day hold 120 s, the stored render left as it is. Night hold 90 s, the same frame multiplied by 0.4, with the picture-book lamp drawn lit: the model has no bulb. On that night model the clock keeps a steady amber dot for the whole hold. The day model does not. Pause before the next one: 1800 s. It stays up when something is seen. The window shows the model; the classification rectangle is not drawn on it. Bottom left, a line reads OPENSTREETMAP ODBL. Bottom right, about a quarter of the window, the live picture remains, with the word DIRECT and a red dot that blinks each second. Dancers, carpet, elephant and bear stay off this view. The Pi opens a picture it already has.",
    stillEclat: "A good catch is a name at confidence 0.60 or above while the thing is still in the picture: car, walker, bike, bus, truck, plane. A published class below that bar still counts on the day reels. The stream sits a few seconds behind the watch, so the cheer waits until the subject is on screen and the rectangle is drawn. GOOD CATCH! crosses in green for 1.6 s. A white flash dies in 0.5 s. The letterbox takes the colour of that kind of passage for 3.5 s, and the name is written large under the picture. Pixel, grey and wave hold off for 4 s. During the flyover the rectangle stays with the live inset.",
    stillRencontre: "Two puppets stand in the lower corners when the music is pushing, drawn at half opacity. They meet every 419 s, with a 90 s offset. Glide 4 s each way, hold 6 s in the middle. Between meetings they step into the black bands: period 180 s, slide 3 s, hold 5 s. During a flyover they are left off the relief.",
    stillVersion: "For the whole session, while a track plays. A cyan pill sits beside NOW PLAYING and reads v followed by the number in the watcher. This build is v0.6.24. The type is Hershey simplex at 0.44 of the 1600 px reference, in a frame filled at 0.22 of cyan and stroked at 0.70. The same number is written into events.json at each publish, and the footer of this page reads it back.",
    stillDeploy: "On stream start, for 6 s, centred at 40% of the frame height. It rises over 0.6 s and leaves over 0.8 s. Two cyan lines, Hershey duplex: DEPLOYED at size 1.15, and v plus the version at size 1.8, 88 px lower at the 1600 px reference. A voice says Deployed. Four fifths of that voice pass straight through. The rest is multiplied by a 90 Hz tone. After the six seconds the lines leave. The pill on the console is what keeps the number.",
    stillFriend: "Once a day, at 7:15 Europe/Paris. Grace 240 s: a restart inside those four minutes does not say it twice, and past the window the day stays quiet. The voice says: To my very good friend David Vincent or Vincent David or David Vincent, Je pense à toi. The line DAVID VINCENT OR VINCENT DAVID stays written for 17 s.",
    stillDijon: "A collaboration. Twice a day, at 23:00 and at 23:15 Europe/Paris. Grace 240 s: a restart does not repeat a slot, and a missed slot is closed. Hold 14 s. Fade 0.5 s in and 0.7 s out. The camera window is graded toward mustard, BGR (36, 164, 214), at strength 0.55. The line reads UNE COLLAB. The hour is written above the logo. At 23:00 a voice says Il est vingt-trois heures à Dijon. At 23:15 it says Il est vingt-trois heures quinze à Dijon.",
    stillTapis: "Period 397 s, crossing 14 s, no start delay. Gate: the music is pushing, and the stage is free at the start of the turn; otherwise the turn is skipped. At night the period is divided by 3. The carpet crosses the whole frame, black bands included, and follows the crest so it clears the summit. The figure is the same puppet as the corners.",
    stillMarin: "Period 523 s, crossing 22 s, no start delay. No music gate: it crosses above the road whether the music is pushing or the slope is quiet. At night the period is divided by 3. It follows the crest and pitches by a tenth of its height, two and a half times during the crossing. If the drawing is missing on the Pi, the crossing does not happen.",
    stillPiste: "Period 787 s, descent 20 s. At night the period is divided by 3. The line is the André Philip run as OpenStreetMap records it, projected with the camera pose and the terrain. White is drawn behind him and fades ahead of him. Five turns, a weave of 2.6 times his size. Height 0.085 of the view. Same puppet as the corners, smaller because he is far up the slope.",
    stillElephant: "Period 661 s, hold 4 s. Only from 01:00 to 06:00. Gate: the music is pushing, and 300 s have passed with nothing named, because he covers the road. At night the period is divided by 3. He fills about 0.95 of the frame. A trunk to the left, a small solid eye.",
    stillOurs: "Period 8191 s, which is 2 h 16 min 31 s. Not divided at night: the bear keeps his own pace. First turn delayed 90 s, long enough for YouTube to open the picture. Walk 2.6 s from the statue at (0.5698, 0.8593) of the camera window to the island at (0.2304, 0.8706), on a smoothstep. Dance 10 s on the island. The cutout is 72/1920 by 140/1080 of the window, times 43/47 on the island, then swelled to 1.35. During the dance he weeps and the line THIS IS MY HOME!!!!! is drawn in yellow. A small card sits bottom right, colour kept, Gaussian blur of sigma 1.1, label REPLAY · 2025. The sculpture itself does not move.",
    stillSoleil: "Drawn when the sun is up and still behind the ridge, or the weather is cloud, overcast, fog, mist, rain, snow or storm. A circle, eleven uneven rays, a smile, placed where the real sun falls in the frame. If that point is outside the view, it sits in the corner of the sky on the side where the sun is, once the sun is at least 3° up. It breathes, about one turn in 10 s. Drawn before pixel and wave, so those treatments take it with the mountain.",
    stillLamp: "At night, once the sun is at or below the horizon. The pole follows the measured mast, 7 m, from foot to shoulder, and the bracket runs to the lantern the map places on the bulb. Its length in the picture comes from that height, the distance and the lens. The glow is the lamp’s own light, turned up around the bulb, and it breathes slowly. A camera whose pole was never measured gets no lamp. Drawn before pixel and wave.",
    cannesTitle: "Cannes",
    cannesLead: "On 6 October 2026 at 08:49 Europe/Paris the Mont Serein playlist closed. Its last segment is dated 2026-10-06T06:49:04Z and the file carries #EXT-X-ENDLIST. A live playlist does not. The broadcast stayed up and opened the other camera in the collection.",
    cannesBackup: "That camera is the municipal live on Boulevard du Midi, aimed at Les plages du Midi. A side thread reads the Mont Serein playlist every 60 s, off the frame loop. End of list, or a last segment older than 120 s, replaces the picture with Cannes. Cannes is opened 60 s behind its live edge, then held at one second of film per second of clock. The line reads Backup webcam, Cannes. Waiting for Mont Serein. When the playlist is live again, the next frame closes Cannes and opens Mont Serein. The YouTube output is not restarted for that switch.",
    cannesDuplex: "While Mont Serein is the picture, Cannes appears in turn, for 90 s. The first time is 75 s after the stream opens. The next starts 900 s after this one ends, and the two shapes alternate. One is the same page as Mont Serein, with the Cannes picture and the right card turned into Cannes: the counter stays at the bottom right, and the disc is the Hôtel Le Splendid. The other is one row, left to right: the Los Angeles card, the Mont Serein picture, the Beaumont card, the Cannes picture, and the right cartouche for Cannes. The cards keep the cartouche width, so the two pictures are narrower. Each picture keeps its whole frame, letterboxed in its column. The day ratios stay on Los Angeles and Beaumont. The Cannes decoder opens 25 s before, at 640×360, 180 s behind. It does not run during a flyover, a replay, a frozen playlist, or while Cannes already fills the frame.",
    cannesMotion: "Mont Serein has a distance grid built from OpenStreetMap, from node/6410397171. A named box uses the metres that grid measures. Cannes is node/14255983894, at 43.5467593, 6.9754344, bearing 190°, on a pole on Boulevard du Midi. That node has no height, and this frame has no fitted distance grid: nothing has been matched between the picture and the map. The frame is cut into zones: a short piece of road at the bottom right, the sidewalk, the beach, the sea, and the sky. Motion on the sea or the beach is not sent to YOLO. A change over 35% of the frame is dropped, which is how a field of waves can hide a real passage. A rectangle is drawn on the camera it was measured on. It is not copied onto the other column.",
    reliefNoteCannes: "Node 14255983894, bearing 190°, on a pole on Boulevard du Midi. The pole height is not on the map, so this view sits above the ground. The field of view is the page’s, not the webcam’s: it has not been fitted.",
    cannesEffects: "Bear, carpet, submarine, piste, elephant and buildings know the roundabout, the crest and the sheepfold. They are drawn on the Mont Serein picture, and they stay off when Cannes fills the frame. Dancers are drawn on that same Mont Serein picture, and on the whole frame when Cannes has replaced it. Bubbles and fish are drawn on every column that is on screen.",
    stillBati: "Period 1061 s, hold 14 s. At night the period is divided by 3. One building at a time, the five widest in turn. The footprint comes from OpenStreetMap and the roof height from the terrain model, both projected: the foot, then the walls, then the roof. The stroke draws itself, holds, and fades. The sheepfold runs past the right edge of the camera window, and the wire continues into the black band, at the place that wall would occupy if the camera saw wider.",
    stillReplay: "Gate: 300 s with nothing named. Hold 10 s. Pause 600 s before another. Only a passage marked accepted can return. On air the picture is greyed and blocked, at most 24 blocks; the file on disk stays sharp. It is enlarged at most 3 times, and kept within 0.32 of the width. The card is amber, with the word replay and the date. A sung line announces it. The moment something new is seen, the archive leaves.",
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
    reliefOsm: "Data © OpenStreetMap contributors, ODbL",
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
    pipelineLead: "1 image/s depuis la webcam. MOG2 sur une image à 640 px. Une tache compacte tenue 3 images est découpée. YOLO11s, ONNX, nomme la découpe. Le rectangle revient sur l’image d’origine. Le cadre est encodé vers YouTube. Quand la playlist du Mont Serein se ferme, ce cadre est la webcam de Cannes.",
    numbers: "Sur le flux",
    numbersLead: "Un numéro à la fois. Un tour n’est pris que si la scène est libre à l’instant où il commence ; sinon le tour entier est sauté. Les périodes sont des nombres premiers. La nuit, chaque période de cette scène sauf celle de l’ours est divisée par 3, et le retard de départ l’est du même facteur. Pixel, gris et onde sont un autre tirage, hors de cette scène. L’ours garde sa cadence. Chaque ligne ci-dessous est ce qui est dessiné, avec sa période, sa durée et sa porte, mesurées sur le code qui tourne.",
    effectColName: "Nom",
    effectColWhat: "Ce qui se passe",
    effectDay: "Journée",
    effectWire: "Fil",
    effectBubbles: "Bulles",
    effectFish: "Poissons",
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
    effectReplay: "Rediffusion",
    effectMeet: "Rencontre",
    effectVersion: "Version",
    effectDeploy: "Déployé",
    effectFriend: "Pensée",
    effectDijon: "Dijon",
    musicTitle: "Dogmazic",
    musicLead: "Dogmazic est une bibliothèque de musique libre. Les artistes gardent leurs droits et choisissent une licence Creative Commons : un flux peut jouer l’œuvre en public s’il nomme l’auteur, le titre, la licence et un endroit où trouver le fichier. Quatorze heures et treize minutes tournent ici, cent cinquante-huit morceaux, tous issus de cette bibliothèque. Quatre heures en sont l’album Mont Serein 002, écrit pour ce projet. La playlist est publique.",
    rebuild: "Reconstruit",
    rebuildLead: "ffmpeg lit la webcam à 1 image/s. MOG2 tourne à 640 px. Une tache compacte tenue 3 images est découpée. YOLO11s, ONNX, nomme la découpe. Le rectangle est redessiné sur l’image d’origine. Les encarts restent dans les bandes. Le cadre est encodé vers YouTube.",
    watchPi: "4 cœurs, Los Angeles. Il lit l’image, tient l’archive, mixe la musique, dessine les encarts, et pousse le cadre. Température et charge restent sur son encart.",
    watchMotion: "MOG2. Image à 640 px. Un changement sur plus de 35 % du cadre est traité comme de la lumière et écarté. La balise rouge du sommet est masquée.",
    watchClass: "YOLO11s, ONNX, seulement sur la découpe. Voiture, piéton, vélo, camion, bus.",
    watchEffectsTitle: "Effets",
    watchEffects: "Dessinés sur le cadre. Le tableau plus bas donne la période, la durée et la porte de chacun.",
    watchMusicTitle: "Musique",
    watchMusic: "Le Pi choisit le morceau et le baisse sous une voix. Sous l’image : la pochette précédente, le morceau en cours, les deux suivants, l’artiste, le titre, la licence, l’égaliseur.",
    watchOut: "Le cadre est encodé et envoyé à YouTube.",
    listen: "Écouter sur Dogmazic",
    radio: "Flux audio",
    radioOn: "À l’écoute",
    chipFps: "1 image / s",
    story: "La veille",
    heroLead: "Un Raspberry Pi 5 à Los Angeles lit la webcam du Mont Serein, une image par seconde, trouve le mouvement avec OpenCV, nomme ce qui a bougé avec YOLO, et reconstitue l’image en direct YouTube. Quand cette playlist se ferme, le cadre est la webcam de Cannes, boulevard du Midi. La veille est le travail. Le flux est le spectacle.",
    heroMachine: "Quatre cœurs sur un bureau, à neuf mille kilomètres du col. Le Pi tient l’archive, mixe la musique, dessine les encarts et pousse le cadre entier vers YouTube en continu.",
    heroSee: "Les véhicules et les piétons sont plus avancés. La faune, les oiseaux, les avions croisés avec OpenSky et les animaux de compagnie sont encore en cours d’apprentissage. Le modèle cherche à tout voir et à tout nommer juste.",
    heroMusic: "Quatorze heures et treize minutes de musique libre tournent toute la journée, entièrement chez Dogmazic. Quatre heures en sont l’album Mont Serein 002, écrit pour ce projet. Cent cinquante-huit morceaux tiennent dans une playlist publique, à un clic.",
    stage: "Sur le flux",
    stageLead: "Pixel, gris et onde partagent un tirage. Un survol filmé du relief prend la fenêtre quand la route est vide. Les autres lignes sont les numéros.",
    stillConsole: "Tant qu’un morceau joue, une console occupe toute la largeur sous l’image : la pochette qui vient de finir, celle qui joue, et les deux suivantes. Avec le morceau en cours : l’artiste, le titre, la licence et le domaine du fichier. Un égaliseur suit la musique. Le numéro de version reste pendant la session. L’horloge est le compte des images, pas les octets qui attendent dans l’encodeur, donc le crédit correspond à ce qu’on entend.",
    stillDay: "Encart de gauche, America/Los_Angeles. Encart de droite, Europe/Paris, Beaumont-du-Ventoux. Les calendriers ont environ neuf heures d’écart, donc passé minuit en France les deux dates diffèrent. Trois chiffres sous chaque encart : la partie entière du rapport du jour fois 100. Sans mouvement, on lit 000. Sous les chiffres, en petit gris, les prises sur les mouvements. Une classe publiée compte dès qu’elle est nommée, sur les deux calendriers, à la date en cours de chaque côté : vehicle, car, truck, bus, person, cycle, plane, aircraft, animal. Le meilleur rapport est vert. À égalité, les deux restent blancs. L’acclamation verte attend une confiance de 0,60. Au minuit d’un seul côté, la ligne NEW DAY IN LOS ANGELES ou NEW DAY IN BEAUMONT tient 8 s, et seule cette vitre revient à 000.",
    stillFil: "Un fil relie les deux encarts pendant toute la session. Il n’est pas sur l’horloge de la scène. Il part du coin bas de chaque encart, descend dans la bande noire, passe sur une poulie de rayon 7 px à la référence de 1600 px, et traverse 28 px sous la fenêtre caméra. Le creux au repos est de 6 px. Les encarts flottent en opposition, et le fil se creuse et se tend avec ce flottement.",
    stillBulles: "Toujours là, dans les bandes noires, huit bulles de chaque côté. Une bulle est un anneau clair. Son rayon passe de 5 px à 10 px, à la référence de 1600 px, en montant. La plus lente met 8,9 s, la plus vive 4,9 s. La dérive latérale est de 11 px. L’opacité culmine à 0,55. Elles sont dessinées en premier, donc les encarts, les pantins et la fenêtre caméra passent devant.",
    stillPoissons: "Trois poissons traversent ces bandes. Périodes 71 s, 97 s et 127 s, premières entre elles. Chaque poisson n’est dessiné que sur les 0,45 premiers de sa période, donc les bandes sont souvent vides. Un tour il monte, le suivant il plonge, et il change de bande à chaque tour. Longueur 58 px à la référence de 1600 px, opacité 0,9. Les pixels qui tomberaient sur la fenêtre caméra sont effacés avant le mélange. Si la fenêtre touche déjà le bord du cadre, les poissons restent absents.",
    stillPixel: "Toutes les 420 s, un traitement est tiré parmi cinq cases, dont deux vides, donc la photographie reste souvent elle-même. La case se déduit du seul indice du bloc, donc un redémarrage reprend le même traitement. Le pixel tient 20 s et fond en 3,5 s à chaque bout. L’image est réduite à 26 colonnes puis agrandie au plus proche. Pixel, gris et onde ne s’empilent pas. Ils se taisent pendant 4 s après qu’un sujet nommé est à l’écran.",
    stillGris: "Même tirage que le pixel, mêmes 20 s, même fondu de 3,5 s. La couleur se mélange à la luminance perçue : un ciel bleu et un versant vert de même moyenne arithmétique n’ont pas la même clarté, et le mélange suit cette clarté. À pleine force le versant est gris, puis la couleur revient.",
    stillOndule: "Même tirage que le pixel. Vingt-huit bandes horizontales glissent de côté, jusqu’à 3 % de la largeur. Le Pi décale des lignes entières. On ne recalcule pas chaque pixel : cela referait deux cartes de deux millions de flottants à chaque image, pendant l’encodage.",
    stillFly: "Porte : 300 s sans rien de nommé, et aucune rediffusion à l’écran. Le relief prend la fenêtre et ne bouge pas, au point de vue de la webcam. Tenue de jour 120 s, le rendu stocké tel quel. Tenue de nuit 90 s, la même image multipliée par 0,4, avec le lampadaire de livre d’images allumé : la maquette n’a pas d’ampoule. Sur cette maquette de nuit, l’horloge garde un point ambre fixe pendant toute la tenue. La maquette de jour n’en a pas. Pause avant le suivant : 1800 s. Il reste quand la veille voit quelque chose. La fenêtre montre la maquette ; le rectangle de classification n’y est pas dessiné. En bas à gauche, une ligne lit OPENSTREETMAP ODBL. En bas à droite, environ un quart de la fenêtre, le direct reste, mot DIRECT, point rouge qui bat à la seconde. Danseurs, tapis, éléphant et ours restent hors de cette vue. Le Pi ouvre une image qu’il a déjà.",
    stillEclat: "Un good catch est un nom à confiance 0,60 ou plus, pendant que la chose est encore dans l’image : voiture, piéton, vélo, bus, camion, avion. Une classe publiée sous cette barre compte quand même sur les vitres du jour. Le flux a quelques secondes de retard sur la veille, donc l’acclamation attend que le sujet soit à l’écran et que le rectangle soit dessiné. GOOD CATCH! traverse en vert pendant 1,6 s. Un éclair blanc s’éteint en 0,5 s. La bande autour de la fenêtre prend la couleur de ce genre de passage pendant 3,5 s, et le nom s’écrit en grand sous l’image. Pixel, gris et onde se taisent 4 s. Pendant le survol, le rectangle reste avec l’encart du direct.",
    stillRencontre: "Deux pantins dans les coins bas quand la musique pousse, dessinés à demi d’opacité. Ils se rejoignent toutes les 419 s, avec un décalage de 90 s. Glisse 4 s à l’aller comme au retour, tenue 6 s au milieu. Entre deux rencontres ils sortent dans les bandes noires : période 180 s, glisse 3 s, tenue 5 s. Pendant un survol, ils restent hors du relief.",
    stillVersion: "Pendant toute la session, tant qu’un morceau joue. Une pastille cyan se pose à côté de NOW PLAYING et lit v suivi du numéro du veilleur. Cette livraison est v0.6.24. Le caractère est Hershey simplex à 0,44 de la référence de 1600 px, dans un cadre rempli à 0,22 du cyan et tracé à 0,70. Le même numéro est écrit dans events.json à chaque publication, et le pied de cette page le relit.",
    stillDeploy: "Au démarrage du flux, pendant 6 s, centré à 40 % de la hauteur. Il monte en 0,6 s et s’en va en 0,8 s. Deux lignes cyan, Hershey duplex : DEPLOYED à la taille 1,15, et v plus la version à la taille 1,8, 88 px plus bas à la référence de 1600 px. Une voix dit Deployed. Les quatre cinquièmes de cette voix passent tels quels. Le reste est multiplié par une porteuse à 90 Hz. Au bout des six secondes les lignes s’en vont. La pastille de la console est ce qui garde le numéro.",
    stillFriend: "Une fois par jour, à 7 h 15, Europe/Paris. Grâce 240 s : un redémarrage dans ces quatre minutes ne la redit pas, et passé la fenêtre la journée reste silencieuse. La voix dit : To my very good friend David Vincent or Vincent David or David Vincent, Je pense à toi. La ligne DAVID VINCENT OR VINCENT DAVID reste écrite 17 s.",
    stillDijon: "Une collaboration. Deux fois par jour, à 23:00 et à 23:15, Europe/Paris. Grâce 240 s : un redémarrage ne répète pas un créneau, et un créneau manqué est fermé. Tenue 14 s. Fondu 0,5 s à l’entrée et 0,7 s à la sortie. La fenêtre est poussée vers la moutarde, BGR (36, 164, 214), à la force 0,55. La ligne dit UNE COLLAB. L’heure s’écrit au-dessus du logo. À 23:00 une voix dit Il est vingt-trois heures à Dijon. À 23:15 elle dit Il est vingt-trois heures quinze à Dijon.",
    stillTapis: "Période 397 s, traversée 14 s, pas de retard. Porte : la musique pousse, et la scène est libre au début du tour ; sinon le tour est sauté. La nuit, la période est divisée par 3. Le tapis traverse le cadre entier, bandes noires comprises, et suit la crête pour passer au-dessus du sommet. Le personnage est le même pantin que ceux des coins.",
    stillMarin: "Période 523 s, traversée 22 s, pas de retard. Pas de porte musicale : il passe au-dessus de la route que la musique pousse ou que le versant soit calme. La nuit, la période est divisée par 3. Il suit la crête et tangue d’un dixième de sa hauteur, deux fois et demie pendant la traversée. Si le dessin manque sur le Pi, la traversée n’a pas lieu.",
    stillPiste: "Période 787 s, descente 20 s. La nuit, la période est divisée par 3. Le trait est la piste André Philip telle qu’OpenStreetMap la connaît, projeté avec la pose de la caméra et le terrain. Le blanc se dessine derrière lui et s’efface devant lui. Cinq virages, un louvoiement de 2,6 fois sa taille. Hauteur 0,085 de la vue. Même pantin que les coins, plus petit parce qu’il est loin sur le versant.",
    stillElephant: "Période 661 s, tenue 4 s. Seulement de 01:00 à 06:00. Porte : la musique pousse, et 300 s se sont passées sans rien de nommé, parce qu’il couvre la route. La nuit, la période est divisée par 3. Il occupe environ 0,95 du cadre. Une trompe à gauche, un petit œil plein.",
    stillOurs: "Période 8191 s, soit 2 h 16 min 31 s. Pas divisée la nuit : l’ours garde sa cadence. Premier tour retardé de 90 s, le temps que YouTube ouvre l’image. Marche 2,6 s, de la statue en (0,5698, 0,8593) de la fenêtre jusqu’à l’îlot en (0,2304, 0,8706), en smoothstep. Danse 10 s sur l’îlot. La découpe fait 72/1920 sur 140/1080 de la fenêtre, fois 43/47 sur l’îlot, puis gonflée à 1,35. Pendant la danse il pleure et la ligne THIS IS MY HOME!!!!! s’écrit en jaune. Une petite carte se pose en bas à droite, couleur gardée, flou gaussien d’écart-type 1,1, libellé REPLAY · 2025. La sculpture elle-même ne bouge pas.",
    stillSoleil: "Dessiné quand le soleil est levé et encore derrière la crête, ou que le temps est nuageux, couvert, brouillard, brume, pluie, neige ou orage. Un rond, onze rayons inégaux, un sourire, posé là où le vrai soleil tombe dans le cadre. Si ce point est hors champ, il se pose dans le coin du ciel, du côté où est le soleil, dès qu’il est à au moins 3°. Il respire, environ un tour en 10 s. Dessiné avant le pixel et l’onde, donc ces traitements l’emportent avec la montagne.",
    stillLamp: "La nuit, dès que le soleil est à l’horizon ou en dessous. Le mât suit le poteau mesuré, 7 m, du pied à l’épaule, et la potence va jusqu’à la lanterne que la carte pose sur l’ampoule. Sa longueur dans l’image vient de cette hauteur, de la distance et de l’objectif. La lueur est celle de la lampe, remontée autour de l’ampoule, et elle respire lentement. Une caméra dont le poteau n’a pas été mesuré n’a pas de lampadaire. Dessiné avant le pixel et l’onde.",
    cannesTitle: "Cannes",
    cannesLead: "Le 6 octobre 2026 à 08:49, heure de Paris, la playlist du Mont Serein s’est fermée. Son dernier segment est daté 2026-10-06T06:49:04Z et le fichier porte #EXT-X-ENDLIST. Une playlist en direct ne le porte pas. L’antenne est restée ouverte et a pris l’autre caméra de la collection.",
    cannesBackup: "Cette caméra est le direct municipal du boulevard du Midi, tourné vers les plages du Midi. Un fil à côté lit la playlist du Mont Serein toutes les 60 s, hors de la boucle des images. Fin de liste, ou dernier segment plus vieux que 120 s, et l’image devient Cannes. Cannes s’ouvre à 60 s du bord de son direct, puis une seconde de film par seconde de montre. La ligne dit Backup webcam, Cannes. Waiting for Mont Serein. Quand la playlist est de nouveau en direct, l’image suivante ferme Cannes et rouvre le Mont Serein. La sortie YouTube n’est pas relancée pour ce basculement.",
    cannesDuplex: "Tant que le Mont Serein est l’image, Cannes apparaît à tour de rôle, pendant 90 s. La première fois est 75 s après l’ouverture du flux. La suivante commence 900 s après la fin de celle-ci, et les deux formes alternent. L’une est la même page que le Mont Serein, avec l’image de Cannes et la boîte de droite devenue Cannes : le compteur reste en bas à droite, le médaillon est l’hôtel Le Splendid. L’autre est une rangée, de gauche à droite : la boîte de Los Angeles, l’image du Mont Serein, la boîte de Beaumont, l’image de Cannes, et le cartouche de droite pour Cannes. Les boîtes gardent la largeur du cartouche, les deux images sont plus étroites. Chaque image garde tout son cadre, posée dans sa colonne. Les rapports du jour restent sur Los Angeles et Beaumont. Le décodeur de Cannes s’ouvre 25 s avant, en 640×360, à 180 s de retard. Ça ne joue pas pendant un survol, une rediffusion, une playlist figée, ni quand Cannes occupe déjà tout le cadre.",
    cannesMotion: "Le Mont Serein a une grille de distances tirée d’OpenStreetMap, depuis le nœud 6410397171. Une boîte nommée s’appuie sur les mètres que cette grille mesure. Cannes est le nœud 14255983894, en 43,5467593, 6,9754344, cap 190°, sur un poteau du boulevard du Midi. Ce nœud n’a pas de hauteur, et ce cadre n’a pas de grille calée : rien n’a été apparié entre l’image et la carte. Le cadre est découpé en zones : un bout de route en bas à droite, le trottoir, la plage, la mer, le ciel. Un mouvement sur la mer ou la plage n’est pas envoyé à YOLO. Un changement sur plus de 35 % du cadre est écarté, et c’est ainsi qu’un champ de vagues peut cacher un vrai passage. Un rectangle se dessine sur la caméra où il a été mesuré. Il n’est pas recopié sur l’autre colonne.",
    reliefNoteCannes: "Nœud 14255983894, cap 190°, sur un poteau du boulevard du Midi. La hauteur du poteau n’est pas sur la carte, donc cette vue est au-dessus du sol. Le champ est celui de la page, pas celui de la webcam : il n’a pas été calé.",
    cannesEffects: "L’ours, le tapis, le sous-marin, la piste, l’éléphant et les bâtiments connaissent le rond-point, la crête et la bergerie. Ils se dessinent sur l’image du Mont Serein, et ils restent absents quand Cannes occupe le cadre. Les danseurs se dessinent sur cette même image, et sur le cadre entier quand Cannes l’a remplacée. Les bulles et les poissons se dessinent sur chaque colonne à l’écran.",
    stillBati: "Période 1061 s, tenue 14 s. La nuit, la période est divisée par 3. Un bâtiment à la fois, les cinq plus larges à tour de rôle. L’emprise vient d’OpenStreetMap, la hauteur du toit du modèle de terrain, les deux projetés : le pied, puis les murs, puis le toit. Le trait se dessine, tient, puis s’efface. La bergerie dépasse le bord droit de la fenêtre, et le fil continue dans la bande noire, à l’endroit où ce mur serait si la caméra voyait plus large.",
    stillReplay: "Porte : 300 s sans rien de nommé. Tenue 10 s. Pause 600 s avant la suivante. Seul un passage marqué accepté peut revenir. À l’antenne l’image est grisée et mise en blocs, 24 blocs au plus ; le fichier sur le disque reste net. Agrandie au plus 3 fois, et tenue dans 0,32 de la largeur. La carte est ambre, avec le mot replay et la date. Une ligne chantée l’annonce. Dès que quelque chose de nouveau est vu, l’archive s’en va.",
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
    reliefOsm: "Données © contributeurs OpenStreetMap, ODbL",
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

// The picture can outlive the camera. A closed playlist is a photograph;
// the broadcast on this page keeps going, and the line says so. Two minutes
// without a new segment is the same thing. A short gap is not.
const FIGEE_APRES_S = 120;
const degrade = document.querySelector("#degrade");
const liveMot = document.querySelector("#live-mot");
const liveChip = document.querySelector(".live-chip");

function playlistFigee(texte, maintenant = Date.now()) {
  if (texte.includes("#EXT-X-ENDLIST")) return true;
  const dates = [...texte.matchAll(/#EXT-X-PROGRAM-DATE-TIME:([^\r\n]+)/g)]
    .map((marque) => Date.parse(marque[1]))
    .filter((instant) => Number.isFinite(instant));
  if (!dates.length) return false;
  return (maintenant - dates[dates.length - 1]) / 1000 > FIGEE_APRES_S;
}

async function textePlaylist(url) {
  const reponse = await fetch(url, { cache: "no-store" });
  if (!reponse.ok) throw new Error(String(reponse.status));
  const texte = await reponse.text();
  const ligne = texte.split("\n").map((l) => l.trim()).find((l) => l && !l.startsWith("#"));
  if (!ligne || ligne === url || !ligne.includes(".m3u8")) return texte;
  const suite = ligne.startsWith("http") ? ligne : new URL(ligne, url).href;
  const media = await fetch(suite, { cache: "no-store" });
  if (!media.ok) return texte;
  return media.text();
}

function peintDegrade() {
  // L'autre webcam est le direct. Le bandeau dégradé ne s'allume plus.
  if (degrade) degrade.hidden = true;
  if (liveChip) liveChip.classList.remove("degraded");
  if (liveMot) liveMot.textContent = "LIVE";
}

async function veilleWebcam() {
  try {
    await textePlaylist(STREAM);
    peintDegrade();
  } catch (_) {
    /* The last reading stays. A failed fetch is not a camera. */
  }
}

veilleWebcam();
setInterval(veilleWebcam, 30 * 1000);

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
