{
  description = "allegro-shopping: deterministic Allegro research and basket planning";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
      python = pkgs.python313;
      runtimeLibs = [ pkgs.stdenv.cc.cc.lib pkgs.zlib pkgs.glib ];
      repo = "${self}";
    in {
      devShells.${system}.default = pkgs.mkShell {
        packages = [ python pkgs.uv pkgs.google-chrome pkgs.git ];
        LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath runtimeLibs;
        shellHook = ''
          echo "allegro-shopping devshell: uv sync && uv run allegro-shop doctor"
        '';
      };

      # A wrapper for the checkout, not a sealed store build: the Python
      # environment is the uv venv, which must live in a writable directory.
      # The repo path is explicit (ALLEGRO_SHOP_REPO or the home checkout); a
      # missing venv is an error, never a silent fallback.
      packages.${system}.default = pkgs.writeShellScriptBin "allegro-shop" ''
        set -euo pipefail
        repo="''${ALLEGRO_SHOP_REPO:-$HOME/git/allegro-shopping}"
        if [ ! -d "$repo/.venv" ]; then
          echo "allegro-shop: no uv venv at $repo; run 'uv sync' there" >&2
          exit 1
        fi
        export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath runtimeLibs}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        exec "${pkgs.uv}/bin/uv" run --project "$repo" allegro-shop "$@"
      '';
    };
}
