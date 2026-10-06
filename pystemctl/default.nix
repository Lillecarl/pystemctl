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
  scdoc,
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

  nativeBuildInputs = [ installShellFiles scdoc ];

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
      # scdoc dates the footer from SOURCE_DATE_EPOCH, which the source
      # hook leaves at 1980 for path-copied sources. Pin the man footer
      # date here instead, and bump it when the pages change.
      manEpoch=$(date -u -d "2026-10-06" +%s)
      for page in pystemctl pyjournalctl; do
        SOURCE_DATE_EPOCH=$manEpoch scdoc < ${./man}/$page.1.scd > $page.1
        installManPage $page.1
      done
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
