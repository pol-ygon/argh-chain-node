# 🔥 Argh Chain Node

Welcome to **Argh Chain** — a solar-reactive blockchain protocol.

This guide explains how to install and run a full node locally using Docker.

---

## 📦 Requirements

Make sure you have:

- Docker
- Docker Compose (v2+)
- Git

Check installation:

```bash
docker --version
docker compose version
git --version

git clone https://github.com/pol-ygon/argh-chain-node.git
cd argh-chain

docker compose up --build

```


🌍 Access the Network

Once running:

API → http://localhost:9000

Health check → http://localhost:9000/health


Official Web Wallet:
👉 https://wallet.argh.space

Official Testnet Node:
https://genesis-test.argh.space/chain/latest
