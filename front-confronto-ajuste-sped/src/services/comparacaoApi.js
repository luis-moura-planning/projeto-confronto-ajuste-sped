export async function compararPlanilhaSapSped(planilhaSap, spedContribuicoes) {
  const form = new FormData();
  form.append("planilha_sap", planilhaSap);
  form.append("sped_contribuicoes", spedContribuicoes);

  const res = await fetch("/api/comparar/compara_planilha_sped", {
    method: "POST",
    body: form,
  });

  const data = await res.json();

  if (!res.ok) {
    throw new Error(data.detail ?? "Erro ao processar arquivos.");
  }

  return data;
}
