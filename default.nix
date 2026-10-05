{
  pkgs ? import <nixpkgs> { },
}:
let
  # Python with every project dependency, so the pyrefly bundled into lint
  # below resolves third-party imports through the interpreter on PATH --
  # no search paths stated anywhere, local runs behave like sandbox runs.
  pythonEnv = pkgs.python3.withPackages (ps: [
    ps.anyio
    ps.argcomplete
    ps.jeepney
    ps.platformdirs
    ps.pytest
    ps.systemd-python
  ]);

  # The lint entry point agents run: `nix run --file . lint -- check`
  # verifies, `-- fix` autofixes. Settings come from pystemctl/pyproject.toml
  # by discovery; see lint.sh.
  lint = pkgs.writeShellApplication {
    name = "lint";
    runtimeInputs = [
      pkgs.ruff
      pkgs.pyrefly
      pythonEnv
    ];
    text = builtins.readFile ./lint.sh;
  };

  # The same entry point as a sandbox gate: a writable copy of the source
  # tree, checked from its root, so check mode behaves exactly as it does
  # on a live checkout. Any failure fails the derivation, which fails the
  # package build that takes it as a check input.
  lint-check = pkgs.runCommand "pystemctl-lint-check" { nativeBuildInputs = [ lint ]; } ''
    cp -r ${./pystemctl} source
    chmod -R u+w source
    cd source
    lint check
    touch "$out"
  '';
in
{
  inherit lint lint-check;
  pystemctl = pkgs.python3Packages.callPackage ./pystemctl { lintCheck = lint-check; };
}
