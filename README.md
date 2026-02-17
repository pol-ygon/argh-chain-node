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


## 🌍 Access the Network

Once running:

API → http://localhost:9000

Health check → http://localhost:9000/health


Official Web Wallet:
👉 https://wallet.argh.space

Official Testnet Node:
https://genesis-test.argh.space/chain/latest

## 🧪 Join the Testnet
If you want to participate in the Argh Chain Testnet, please contact us. We need to manually whitelist your public IP address to allow your node to connect to the network.

### 📩 Send us:
Your public IP address
Your node validator address

Once approved, your node will be added to the active testnet peer list.

## 🧹 Stop the Node
```bash
docker compose down
```

## 🔐 Reset Local Chain (if needed)

If you want to fully reset your local node:

```bash
docker compose down
rm -rf data/chain.enc
docker compose up --build
```

---

## ☀️ About Argh Chain

Argh Chain is a deterministic blockchain protocol featuring:

- Solar-flare driven treasury emissions
- Encrypted local chain storage
- Deterministic validator rotation
- Fee distribution system
- Bridge minting for aUSD

Welcome to the sun-reactive economy. 🌞
