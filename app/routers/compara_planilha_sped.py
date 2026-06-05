import io
import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from services.comparacao_planilha_sap_sped import compara_gera_diferenca

router = APIRouter(prefix="/comparar", tags=["Comparação SAP × SPED"])


@router.post("/compara_planilha_sped")
async def comparar(
    planilha_sap: UploadFile = File(..., description="Diário SAP (.xlsx)"),
    sped_contribuicoes: UploadFile = File(..., description="SPED Contribuições (.txt)"),
):
    try:
        conteudo_sap = await planilha_sap.read()
        conteudo_sped = await sped_contribuicoes.read()

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp_sped:
            tmp_sped.write(conteudo_sped)
            path_sped = tmp_sped.name

        try:
            resultado = compara_gera_diferenca(
                arquivo_sped=path_sped,
                planilha_diario=io.BytesIO(conteudo_sap),
            )
        finally:
            os.unlink(path_sped)

        return {
            "divergencias": resultado["divergencias_json"],
            "ok": resultado["ok_json"],
            "so_sped": resultado["so_sped_json"],
            "so_sap": resultado["so_sap_json"],
            "lancamentos": resultado["lancamentos_json"],
        }

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
