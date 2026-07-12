// Webview entry point for the NSCLC Atlas explorer. Bundled by esbuild
// (browser/IIFE) into media/atlas/atlas.bundle.js and mounted by src/atlas.ts.
import { createRoot } from "react-dom/client";
import Home from "./page";

const el = document.getElementById("root");
if (el) createRoot(el).render(<Home />);
