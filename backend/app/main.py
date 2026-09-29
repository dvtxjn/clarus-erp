from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.migrate import run_migrations
from app import models  # noqa: F401 — populates Base.metadata
from app.routers import auth, shipments, documents, hs_codes, proforma, extraction, ports, tracker_columns, challans, final_invoices, tracker_import

app = FastAPI(title="Customs Clearance ERP API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(shipments.router)
app.include_router(documents.router)
app.include_router(hs_codes.router)
app.include_router(proforma.router)
app.include_router(extraction.router)
app.include_router(ports.router)
app.include_router(tracker_columns.router)
app.include_router(challans.router)
app.include_router(final_invoices.router)
app.include_router(tracker_import.router)


@app.on_event("startup")
def on_startup():
    run_migrations()


@app.get("/health")
def health_check():
    return {"status": "ok"}
