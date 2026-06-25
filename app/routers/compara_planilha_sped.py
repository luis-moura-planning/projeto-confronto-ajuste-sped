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
    sap_bytes  = await planilha_sap.read()
    sped_bytes = await sped_contribuicoes.read()

    path_sap  = None
    path_sped = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            f.write(sap_bytes)
            path_sap = f.name

        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(sped_bytes)
            path_sped = f.name

        resultado = compara_gera_diferenca(path_sap, path_sped)

    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if path_sap and os.path.exists(path_sap):
            os.unlink(path_sap)
        if path_sped and os.path.exists(path_sped):
            os.unlink(path_sped)

    return resultado
