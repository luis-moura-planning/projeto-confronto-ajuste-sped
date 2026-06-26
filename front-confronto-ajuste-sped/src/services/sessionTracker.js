const enviarEvento = (tipo) => {
  const meu_app = localStorage.getItem("ultimoApp");
  fetch("/server_php/logger.php", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ tipo, meu_app }),
  })
    .then((res) => res.text())
    .then((text) => {
      try {
        const data = JSON.parse(text);
        if (!data.success) {
          console.error("Falha ao registrar evento:", data.msg || "Erro desconhecido");
        }
      } catch {
        // servidor retornou HTML (ex: redirect de login) — ignora silenciosamente
      }
    })
    .catch((error) => console.error("Erro ao enviar evento:", error));
};

export const initSessionTracker = () => {
  let eventoEnviado = false;

  enviarEvento("entrada");

  const handleVisibilityChange = () => {
    if (eventoEnviado) return;
    if (document.visibilityState === "hidden") {
      enviarEvento("inativo");
    } else if (document.visibilityState === "visible") {
      enviarEvento("reativo");
    }
  };

  const handleBeforeUnload = () => {
    if (eventoEnviado) return;
    const meu_app = localStorage.getItem("ultimoApp");
    navigator.sendBeacon(
      "/server_php/logger.php",
      new URLSearchParams({ tipo: "saida", meu_app }),
    );
    eventoEnviado = true;
  };

  document.addEventListener("visibilitychange", handleVisibilityChange);
  window.addEventListener("beforeunload", handleBeforeUnload);

  return () => {
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    window.removeEventListener("beforeunload", handleBeforeUnload);
  };
};
