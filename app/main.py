from fastapi import FastAPI

from app.routes import w0_health, w1_plaid_sync, w2_llm_categorize, w3_learn_corrections

app = FastAPI(title="Bank Categorizer", version="0.1.0")

app.include_router(w0_health.router)
app.include_router(w1_plaid_sync.router)
app.include_router(w2_llm_categorize.router)
app.include_router(w3_learn_corrections.router)


@app.get("/")
async def root():
    return {"service": "bank-categorizer", "version": "0.1.0"}
