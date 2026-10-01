/* Charge la page, dit ce qu'il se passe, et prend une image. Jetable. */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, resolve } from "node:path";
import puppeteer from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const RACINE = resolve(new URL("..", import.meta.url).pathname);
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json",
                ".css": "text/css", ".jpg": "image/jpeg", ".png": "image/png" };

const serveur = createServer(async (demande, reponse) => {
  const demande_ = decodeURI(demande.url.split("?")[0]);
  const chemin = join(RACINE, "_site", demande_.endsWith("/") ? demande_ + "index.html" : demande_);
  try {
    const corps = await readFile(chemin);
    reponse.writeHead(200, { "content-type": TYPES[extname(chemin)] ?? "application/octet-stream" });
    reponse.end(corps);
  } catch { reponse.writeHead(404); reponse.end(); }
});
await new Promise((p) => serveur.listen(0, "127.0.0.1", p));
const port = serveur.address().port;
console.log("serveur sur", port);

const navigateur = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--hide-scrollbars", "--enable-unsafe-swiftshader", "--no-sandbox"],
});
console.log("chrome lancé");
const page = await navigateur.newPage();
page.on("console", (m) => console.log("  page:", m.text().slice(0, 160)));
page.on("pageerror", (e) => console.log("  ERREUR:", String(e).slice(0, 200)));
page.on("requestfailed", (r) => console.log("  raté:", r.url().slice(0, 100)));
await page.setViewport({ width: 1280, height: 720 });
await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "domcontentloaded", timeout: 30000 });
console.log("page chargée");
try {
  await page.waitForSelector("#relief canvas", { timeout: 40000 });
  console.log("canevas trouvé");
} catch { console.log("PAS DE CANEVAS"); }
await new Promise((p) => setTimeout(p, 4000));
const vide = await page.evaluate(() => {
  const c = document.querySelector("#relief canvas");
  if (!c) return "absent";
  return `${c.width}x${c.height} ctx=${!!c.getContext("webgl2") || !!c.getContext("webgl")}`;
});
console.log("canevas :", vide);
await page.screenshot({ path: "/tmp/vue3d_essai.png" });
console.log("image écrite");
await navigateur.close();
serveur.close();
process.exit(0);
