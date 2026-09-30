{
  pkgs ? import <nixpkgs> { },
}:
{
  pystemctl = pkgs.python3Packages.callPackage ./pystemctl { };
}
