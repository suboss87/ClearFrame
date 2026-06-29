# Clearframe frontend

React + Vite reviewer surface for the Clearframe ad compliance pipeline.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
```

Tailwind utility classes load from the CDN in `index.html`, so there is no
Tailwind build step. Icons come from `lucide-react`.

## Two entry components

- `src/ClearframeApp.jsx` is the full product: bulk upload, the batch review
  dashboard, and the detail reviewer with the evidence timeline. This is the
  default app rendered by `main.jsx`.
- `src/Clearframe.jsx` is the focused single-screen reviewer (queue rail +
  detail), useful for a lean walkthrough where you do not want to click through
  upload progress.

## Demo mode vs live API

`ClearframeApp.jsx` has a constant near the top:

```js
const API_BASE = "";   // empty = standalone demo using built-in sample data
```

Leave it empty and the app simulates the pipeline so it runs with no backend,
which is what you want for a safe live demo. Set it to your running API (for
example `http://localhost:8000`) and uploads post to the real endpoints and
verdicts stream back from the pipeline.
