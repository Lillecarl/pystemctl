{
  lib,
  buildPythonPackage,
  hatchling,
  anyio,
  argcomplete,
  jeepney,
  systemd-python,
  installShellFiles,
  pytestCheckHook,
  stdenv,
}:

buildPythonPackage rec {
  pname = "pystemctl";
  version = "0.1.0";
  pyproject = true;

  src = ./.;

  build-system = [ hatchling ];

  dependencies = [
    anyio
    argcomplete
    jeepney
    systemd-python
  ];

  nativeBuildInputs = [ installShellFiles ];

  nativeCheckInputs = [ pytestCheckHook ];

  postInstall =
    let
      register-python-argcomplete = lib.getExe' argcomplete "register-python-argcomplete";
    in
    lib.optionalString (stdenv.buildPlatform.canExecute stdenv.hostPlatform) ''
      export PATH="$out/bin:$PATH"
      for cmd in pystemctl pyjournalctl; do
        installShellCompletion --cmd "$cmd" \
          --bash <(${register-python-argcomplete} --shell bash "$cmd") \
          --zsh <(${register-python-argcomplete} --shell zsh "$cmd") \
          --fish <(${register-python-argcomplete} --shell fish "$cmd")
      done
    '';

  pythonImportsCheck = [
    "pystemctl"
    "pystemctl.cli"
    "pystemctl.journal"
    "pystemctl.systemd"
  ];

  meta = {
    description = "Python reimplementation of systemctl and journalctl, with helpers for ephemeral user units";
    license = lib.licenses.mit;
    mainProgram = "pystemctl";
  };
}
