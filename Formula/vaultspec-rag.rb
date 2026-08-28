class VaultspecRag < Formula
  desc "Hybrid dense and sparse semantic search for your docs and source code"
  homepage "https://github.com/nevenincs/vaultspec-rag"
  version "0.4.10"
  license "MIT"

  livecheck do
    url :stable
    regex(/^vaultspec-rag-v(\d+(?:\.\d+)+)$/i)
    strategy :github_latest
  end

  on_linux do
    on_intel do
      url "https://github.com/nevenincs/vaultspec-rag/releases/download/vaultspec-rag-v0.4.10/vaultspec-rag-x86_64-unknown-linux-gnu"
      sha256 "95499c32495be0952b76dc6f9b297ff1b8f78f1e91267862b51faf60ab4b7902"

      resource "vaultspec-search-mcp" do
        url "https://github.com/nevenincs/vaultspec-rag/releases/download/vaultspec-rag-v0.4.10/vaultspec-search-mcp-x86_64-unknown-linux-gnu"
        sha256 "f92e1cf76059224121d5d40b420f924528547def4f884114ba630bbaaf1d9acd"
      end
    end
  end

  def install
    vendor = OS.mac? ? "apple-darwin" : "unknown-linux-gnu"
    arch = Hardware::CPU.arm? ? "aarch64" : "x86_64"
    triple = "#{arch}-#{vendor}"

    bin.install "vaultspec-rag-#{triple}" => "vaultspec-rag"

    resource("vaultspec-search-mcp").stage do
      bin.install "vaultspec-search-mcp-#{triple}" => "vaultspec-search-mcp"
    end
  end

  def caveats
    <<~EOS
      Requires an NVIDIA GPU with a working CUDA driver; there is no CPU mode.
      First launch downloads the CUDA runtime; needs network once, and space.
      Same GPU torch build uv installs, pinned from this project's lock.
      Verify with: vaultspec-rag --version
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/vaultspec-rag --version")
  end
end
