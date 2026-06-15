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
        conteudo_sap  = await planilha_sap.read()
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
            "divergencias": (
                resultado["divergencias_saida_json"]
                + resultado["divergencias_entrada_json"]
                + resultado["divergencias_transporte_json"]
                + resultado["divergencias_f100_json"]
                + resultado["divergencias_c500_json"]
            ),
            "ok": (
                resultado["ok_saida_json"]
                + resultado["ok_entrada_json"]
                + resultado["ok_transporte_json"]
                + resultado["ok_f100_json"]
                + resultado["ok_c500_json"]
            ),
            "so_sped": (
                resultado["so_sped_saida_json"]
                + resultado["so_sped_entrada_json"]
                + resultado["so_sped_transporte_json"]
                + resultado["so_sped_f100_json"]
                + resultado["so_sped_c500_json"]
                + resultado["so_sped_m_json"]
                + resultado["so_sped_f120_json"]
            ),
            "so_sap": (
                resultado["so_sap_saida_json"]
                + resultado["so_sap_entrada_json"]
                + resultado["so_sap_transporte_json"]
                + resultado["so_sap_f100_json"]
                + resultado["so_sap_c500_json"]
            ),
            "lancamentos":                resultado["lancamentos_json"],
            "lancamentos_so_sped":        resultado["lancamentos_so_sped_json"],
            "lancamentos_estorno_so_sap": resultado["lancamentos_estorno_so_sap_json"],
            "lancamentos_m110_m510":      resultado["lancamentos_m110_m510_json"],
            "lancamentos_m215_m615":      resultado["lancamentos_m215_m615_json"],
            "lancamentos_f120":           resultado["lancamentos_f120_json"],
        }

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
