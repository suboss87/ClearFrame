# Clearframe developer commands. Run from the repo root.

.PHONY: install test eval demo seed api web

install:        ## install backend and frontend deps
	cd backend && pip install -r requirements.txt
	cd frontend && npm install

test:           ## run the decision-engine unit tests
	cd backend && python tests/test_decision.py

eval:           ## score the decision engine against the labeled set (precision/recall)
	cd backend && python eval/run_eval.py --md REPORT.md

demo:           ## run the pipeline over the four sample creatives (mock mode)
	cd backend && python -m demo.run_demo --html

seed:           ## reset the DB to one demo campaign with four sample creatives
	cd backend && python seed_demo.py

api:            ## start the FastAPI server on :8000
	cd backend && uvicorn api:app --reload

web:            ## start the Vite dev server on :5173
	cd frontend && npm run dev
