from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.types import Message

router = APIRouter(prefix="/comparar", tags=["Comparação SAP × SPED"])


@router.post("/compara_planilha_sped")
async def comparar(
    planilha_sap: UploadFile = File(..., description="Diário SAP (.xlsx)"),
    sped_contribuicoes: UploadFile = File(..., description="SPED Contribuições (.txt)"),
):
    return
