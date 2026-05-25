from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.compara_planilha_sped import router as comparar_router

app = FastAPI(title='Confronto SAP × SPED', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173'],
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(comparar_router)

@app.get("/", tags=["Root"])
async def root():
    return {"message": "Compara Planilha Speed  Versão 0.1"}

