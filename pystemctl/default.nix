{
  lib,
  buildPythonPackage,
  hatchling,
  anyio,
  argcomplete,
  jeepney,
  platformdirs,
  systemd-python,
  installShellFiles,
  pytestCheckHook,
  stdenv,
  lintCheck,
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
    platformdirs
    systemd-python
  ];

  nativeBuildInputs = [ installShellFiles ];

  nativeCheckInputs = [ pytestCheckHook lintCheck ];

  postInstall =
    let
      register-python-argcomplete = lib.getExe' argcomplete "register-python-argcomplete";
    in
    ''
      # Installed by hand: the pinned nixpkgs predates the installAgentSkills
      # hook (NixOS/nixpkgs#558216). The layout is the one that hook
      # standardizes (NixOS/nixpkgs#547426: share/skills/$pname/<skill>),
      # so the switch is one line when the pin catches up.
      install -Dm444 ${./skills/pystemctl/SKILL.md} \
        $out/share/skills/pystemctl/pystemctl/SKILL.md
    ''
    + lib.optionalString (stdenv.buildPlatform.canExecute stdenv.hostPlatform) ''
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
