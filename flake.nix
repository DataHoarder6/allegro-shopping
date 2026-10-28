{
  description = "allegro-shopping: deterministic Allegro research and basket planning";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
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
      # Install with home-manager: allegro-shop = inputs.allegro-shopping.packages.${system}.default;
      packages.${system}.default = pkgs.writeShellScriptBin "allegro-shop" ''
        set -euo pipefail
        repo="''${ALLEGRO_SHOP_REPO:-${repo}}"
        if [ ! -d "$repo/.venv" ] && [ ! -d "$HOME/git/allegro-shopping/.venv" ]; then
          echo "allegro-shop: no uv venv; run 'uv sync' in $repo" >&2
          exit 1
        fi
        if [ ! -d "$repo/.venv" ]; then repo="$HOME/git/allegro-shopping"; fi
        export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath runtimeLibs}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        exec "${pkgs.uv}/bin/uv" run --project "$repo" allegro-shop "$@"
      '';
    };
}
