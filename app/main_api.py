from fastapi import FastAPI, APIRouter


from app.routers.compara_planilha_sped import router as comparar_router

app = FastAPI(title='Confronto SAP × SPED', version='1.0.0')

app.include_router(comparar_router)

@app.get("/", tags=["Root"])
async def root():
    return {"message": "Compara Planilha Speed  Versão 0.1"}

