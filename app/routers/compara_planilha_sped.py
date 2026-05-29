import json
import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from services.compara_valores_diario_sped import comparar_por_nota
from services.extrai_dados_planilha_sap import extrair_por_nota as sap_extrai
from services.extrai_dados_sped import extrair_por_nota as sped_extrai
from services.gera_lancamentos_diferenca import gerar_lancamentos_diferenca

router = APIRouter(prefix="/comparar", tags=["Comparação SAP × SPED"])


@router.post("/compara_planilha_sped")
async def comparar(
    planilha_sap: UploadFile = File(..., description="Diário SAP (.xlsx)"),
    sped_contribuicoes: UploadFile = File(..., description="SPED Contribuições (.txt)"),
    filial: str = Form(default=""),
    mapeamento: str = Form(
        default="{}",
        description="JSON {chave_sap: chave_sped} para casos onde a normalização automática não basta",
    ),
):
    try:
        mapeamento_dict: dict = json.loads(mapeamento)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail=f"mapeamento JSON inválido: {exc}"
        ) from exc

    # Salva arquivos em disco temporário para as funções de serviço que lêem por caminho
    with tempfile.TemporaryDirectory() as tmpdir:
        sap_path = os.path.join(tmpdir, "sap.xlsx")
        sped_path = os.path.join(tmpdir, "sped.txt")

        with open(sap_path, "wb") as f:
            f.write(await planilha_sap.read())
        with open(sped_path, "wb") as f:
            f.write(await sped_contribuicoes.read())

        try:
            notas_sap = sap_extrai(sap_path)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Erro ao ler planilha SAP: {exc}"
            ) from exc

        try:
            notas_sped = sped_extrai(sped_path)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Erro ao ler arquivo SPED: {exc}"
            ) from exc

    comparacao = comparar_por_nota(notas_sap, notas_sped, mapeamento_dict)

    lancamentos = gerar_lancamentos_diferenca(comparacao, filial=filial)

    encontrados = sum(1 for v in comparacao.values() if v["status"] == "encontrado")
    sem_sped = sum(1 for v in comparacao.values() if v["status"] == "sem_sped")
    sem_sap = sum(1 for v in comparacao.values() if v["status"] == "sem_sap")

    return {
        "resumo": {
            "total_notas_sap": len(notas_sap),
            "total_notas_sped": len(notas_sped),
            "encontrados": encontrados,
            "sem_sped": sem_sped,
            "sem_sap": sem_sap,
        },
        "comparacao": comparacao,
        "lancamentos": lancamentos,
    }
