(() => {
  function enhanceBackupValidationForm() {
    const form = document.querySelector("#backup-validation-form");
    if (!form || form.dataset.storageDiscoveryEnhanced === "1") return;
    form.dataset.storageDiscoveryEnhanced = "1";

    for (const name of ["mount_point", "redundancy_path"]) {
      const input = form.querySelector(`[name="${name}"]`);
      input?.closest("label")?.remove();
    }

    const backupInput = form.querySelector('[name="backup_path"]');
    const backupLabel = backupInput?.closest("label");
    const labelText = backupLabel?.querySelector("span");
    if (labelText) labelText.textContent = "Diretório do backup no servidor";
    if (backupInput) backupInput.placeholder = "/u01/backup";

    const grid = form.querySelector(".skill-form-grid");
    if (grid) {
      const note = document.createElement("div");
      note.className = "skill-warning skill-field-wide";
      note.innerHTML = "<strong>Descoberta automática de storage</strong><br>O Agent identifica o filesystem que sustenta o diretório informado, consulta mounts configurados e montados e procura automaticamente a unidade de redundância (NFS, CIFS, NAS, storage ou HD externo).";
      grid.appendChild(note);
    }

    const note = form.querySelector(".skill-run-note");
    if (note) {
      note.textContent = "Você informa o diretório da rotina; ponto de montagem e redundância são descobertos no servidor.";
    }
  }

  const observer = new MutationObserver(enhanceBackupValidationForm);
  document.addEventListener("DOMContentLoaded", () => {
    enhanceBackupValidationForm();
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
