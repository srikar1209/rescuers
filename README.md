# Rescuers: Lost & Found

**Tell us the clues. We tell you where to look first.**

In Koester's dementia incident data, 95% of those found within 24 hours were alive, versus 77% of those found later. These are observed groups, not a causal estimate of search speed. Many were found near the last known point. Lost & Found aims to simulate possible on-foot routes on real terrain, turn them into a search heat map, and update it as clues come in.

Built at HackUMass XIV by team Rescuers.

## How it works

1. **Map:** real Amherst terrain from OpenStreetMap, USGS elevation and NLCD land cover, on a 10 m grid.
2. **Simulate:** 5,000 walkers start at a selected Amherst point and follow the current calibrated rule set for four hours.
3. **Heat map:** grid-cell probabilities show where the walkers may be at a selected time.
4. **Clues:** a sighting, negative camera result, or searched circle reweights the original paths without setting any path's weight to zero.
5. **LLM (optional):** turns free-text clues into draft fields for user review. The walking itself is done by the agent-based model.

The map is a fictional-case prototype and its probabilities are model estimates, not validated operational predictions. The proposed next-best-check feature is not implemented.

Scope: people with dementia on foot.

## Project structure

```
rescuers/
  data/            committed Amherst grid and demo; raw source rasters ignored by git
  scripts/         data download and map viewing scripts
  rescuers/        grid builder, simulator, calibration, and clue inference
  ui/              local 2D map, case forms, evidence API, and server
  environment.yml  conda environment
```

## Run the UI locally

The repository includes `data/grid.npz` and `data/calibrated_params.json`, so you do not need to download GIS files or rebuild the grid to try the UI. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ui.txt
python ui/serve.py --port 8002
```

Open http://127.0.0.1:8002/. Leave the terminal running while you use the page; press Ctrl+C to stop it. If port 8002 is busy, choose another port and open the matching URL. An existing Python environment with NumPy and Pillow also works. The full Conda environment is for rebuilding map data.

See [UI setup and workflow](ui/README.md) for the demo, case and clue controls, optional Gemini setup, and troubleshooting. See [data provenance](data/README.md) for the grid inputs.

## Deploy to Render and sim2find.us

The root `render.yaml` creates a Python web service on Render's Free plan. It installs only the UI dependencies, serves on Render's assigned `PORT`, and checks `/api/health`. `.python-version` selects Python 3.12. The committed Amherst grid is enough to run the app; the raw GIS rasters are not needed.

1. Commit and push the deployment files to the GitHub `main` branch.
2. In [Render](https://dashboard.render.com/), choose **New > Blueprint**, connect `srikar1209/rescuers`, select `main`, and apply the `render.yaml` Blueprint. Wait for the service to say **Live**.
3. Open the assigned `https://sim2find.onrender.com` address, or the actual `.onrender.com` URL Render displays. Check `/api/health` for `"grid": true`, then run the fictional **Demo** case and verify the heatmap loads.
4. In the Render service's **Settings > Custom Domains**, add `sim2find.us`. Render also creates `www.sim2find.us` and redirects it to the root domain.
5. In Porkbun's DNS records for `sim2find.us`, set an **A** record with **Host** blank and **Answer** `216.24.57.1`. Set a **CNAME** with **Host** `www` and **Answer** equal to your service's actual `.onrender.com` hostname. Remove only conflicting old web/parking A, AAAA, CNAME, or forwarding records for those two hosts; keep unrelated records such as MX or TXT. Do not change the nameservers.
6. Back in Render, click **Verify** for the custom domain. After DNS resolves, open `https://sim2find.us` and repeat the demo check.

Render Free services sleep after 15 minutes without traffic; the next request can take about a minute to wake them. Runs are held in memory and disappear when the server restarts or sleeps. Public visitors can create runs, so this is suitable for a hackathon demonstration, not an operational search service. Manual clue entry works without an AI key. To enable Gemini extraction, add `GEMINI_API_KEY` in the Render service's **Environment** settings, never in Git; public use of that endpoint can consume your provider quota.

## Key sources

- [Koester, *Lost Person Behavior*, dementia chapter](https://www.dbs-sar.com/LPB/Dementia.pdf) (ISRID statistics)
- [Koester and Stooksbury (1995)](https://www.dbs-sar.com/SAR_Research/WEM_article.htm), Virginia dementia search incidents
- [Northumbria Police dementia missing-person study](https://tcsr.org.uk/media/2wrpbu4k/2015-a-study-of-people-with-dementia-reported-as-missing-during-2012-and-2013-held-on-the-northumbria-police-integrated-computerised-communications-system.pdf), including a confirmed walking subset

The demo case (Walter) is fictional.
