{
  lib,
  buildPythonPackage,
  hatchling,
  anyio,
  jeepney,
  systemd-python,
  pytestCheckHook,
}:

buildPythonPackage rec {
  pname = "pystemctl";
  version = "0.1.0";
  pyproject = true;

  src = ./.;

  build-system = [ hatchling ];

  dependencies = [
    anyio
    jeepney
    systemd-python
  ];

  nativeCheckInputs = [ pytestCheckHook ];

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
