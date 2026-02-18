# core/network.py

import asyncio
import json
import struct
import time
from core.peer import Peer
from core.block import Block
from config.settings import HOST_IP, HOST_PORT
from core.tx_engine import TransactionEngine

class P2PNetwork:
    def __init__(self, my_node_id, chain, storage, validator, mempool, my_host=HOST_IP, my_port=HOST_PORT):
        self.my_node_id = my_node_id
        self.chain = chain
        self.storage = storage
        self.validator = validator
        self.my_host = my_host
        self.my_port = int(my_port)
        self.peers = {}
        self.syncing = False
        self.sync_target = None 
        self.buffered_blocks = []
        self.mempool = mempool
        self.tx_engine = TransactionEngine()
        self.slot_registry = {}

    def register_block(self, block):
        key = (block.producer_id, block.slot)

        if key in self.slot_registry:
            if self.slot_registry[key] != block.hash:
                return False  # equivocation
        else:
            self.slot_registry[key] = block.hash

        return True

    async def connect_to_nodes(self, nodes: list):
        for node in nodes:
            host = node["host"]
            port = node["port"]

            if node["id"].lower() == self.my_node_id.lower():
                continue

            while True:
                try:
                    reader, writer = await asyncio.open_connection(host, port)

                    await self.send(writer, {
                        "type": "handshake",
                        "node_id": self.my_node_id
                    })

                    msg = await self.read_message(reader)
                    peer_node_id = msg["node_id"]

                    self.peers[peer_node_id] = Peer(peer_node_id, writer)

                    latest_index = len(self.chain) - 1
                    latest_hash = self.chain[-1].hash if self.chain else None

                    await self.send(writer, {
                        "type": "status",
                        "latest_index": latest_index,
                        "latest_hash": latest_hash
                    })

                    asyncio.create_task(
                        self.listen_peer(peer_node_id, reader, writer)
                    )

                    print(f"Connecting to: {host}:{port}")
                    break

                except Exception as e:
                    print(f"❌ Connection failed: {host}:{port}", e)
                    await asyncio.sleep(5)

    async def safe_drain(self, writer, timeout=3):
        try:
            await asyncio.wait_for(writer.drain(), timeout=timeout)
            return True
        except:
            return False

    async def handle_connection(self, reader, writer):
        peer_node_id = None
        try:
            msg = await asyncio.wait_for(self.read_message(reader), timeout=5.0)

            if msg["type"] != "handshake":
                return

            peer_node_id = msg["node_id"]

            if peer_node_id == self.my_node_id:
                return

            if peer_node_id in self.peers:
                return

            await self.send(writer, {
                "type": "handshake",
                "node_id": self.my_node_id
            })

            await self.send(writer, {
                "type": "status",
                "latest_index": len(self.chain) - 1,
                "latest_hash": self.chain[-1].hash
            })

            self.peers[peer_node_id] = Peer(peer_node_id, writer)
            print(f"Peer connected: {peer_node_id}")

            while True:
                msg = await self.read_message(reader)
                await self.handle_message(peer_node_id, msg)

        except (asyncio.TimeoutError, json.JSONDecodeError, UnicodeDecodeError, asyncio.IncompleteReadError):
            pass  # Invalid or incomplete handshake, close silently
        except Exception as e:
            if peer_node_id:
                print(f"❌ Peer {peer_node_id} disconnected: {e}")
        finally:
            if peer_node_id:
                self.peers.pop(peer_node_id, None)
            writer.close()

    # --------------------
    # TCP HELPERS
    # --------------------
    async def broadcast(self, msg: dict):
        raw = json.dumps(msg).encode()
        header = struct.pack(">I", len(raw))

        dead_peers = []

        for peer_id, peer in list(self.peers.items()):
            try:
                peer.writer.write(header + raw)
                ok = await asyncio.wait_for(peer.writer.drain(), timeout=3)
            except Exception as e:
                print(f"❌ Broadcast failed {peer_id}: {e}")
                dead_peers.append(peer_id)
                
        for peer_id in dead_peers:
            self.peers.pop(peer_id, None)

    async def listen_peer(self, peer_id, reader, writer):
        try:
            while True:
                msg = await self.read_message(reader)
                await self.handle_message(peer_id, msg)
        except Exception as e:
            print(f"❌ Peer {peer_id} disconnected", e)
        finally:
            self.peers.pop(peer_id, None)
            writer.close()

    async def send(self, writer, msg: dict):
        raw = json.dumps(msg).encode()
        header = struct.pack(">I", len(raw))
        writer.write(header + raw)

        try:
            await asyncio.wait_for(writer.drain(), timeout=3)
        except Exception:
            raise

    async def read_message(self, reader):
        header = await reader.readexactly(4)
        size = struct.unpack(">I", header)[0]
        payload = await reader.readexactly(size)
        return json.loads(payload.decode())
        
    async def handle_message(self, peer_id, msg):
        print(msg)
        if msg["type"] == "status":
            await self.on_status(peer_id, msg)

        elif msg["type"] == "get_blocks":
            await self.on_get_blocks(peer_id, msg)

        elif msg["type"] == "blocks":
            await self.on_blocks(peer_id, msg)

        elif msg["type"] == "block":
            await self.on_block(peer_id, msg)

        elif msg["type"] == "get_block":
            await self.on_get_block(peer_id, msg)

        elif msg["type"] == "single_block":
            await self.on_single_block(peer_id, msg)

        elif msg["type"] == "tx":
            tx = msg["data"]

            # --------------------------------------------------
            # FLARE REVEAL (special protocol tx)
            # --------------------------------------------------
            if tx.get("action") == "flare_reveal":

                required = ("txid", "commit", "payload", "sender", "chainId")
                for k in required:
                    if k not in tx:
                        return

                added = self.mempool.add(tx)
                if not added:
                    return

                print(f"Accepted FLARE_REVEAL TX: {tx['txid']}")

                await self.broadcast_except(peer_id, {
                    "type": "tx",
                    "data": tx
                })
                return

            required_common = ("txid", "action", "amount", "chainId", "asset")
            for k in required_common:
                if k not in tx:
                    return

            if tx["amount"] <= 0:
                return

            # transfer → to
            if tx["action"] not in ("transfer", "mint", "burn", "add_liquidity", "mint_bridge"):
                return

            # add_liquidity → asset_paired + amount_paired
            if tx["action"] == "add_liquidity":
                if not tx.get("asset_paired"):
                    return
                if not tx.get("amount_paired"):
                    return

            # timestamp
            if not tx.get("timestamp"):
                tx["timestamp"] = int(time.time())

            added = self.mempool.add(tx)
            if not added:
                return

            print(f"Accepted TX through gossip: {tx['txid']}")

            # Broadcast (fan-out)
            await self.broadcast_except(peer_id, {
                "type": "tx",
                "data": tx
            })

        elif msg["type"] == "ping":
            await self.send(self.peers[peer_id].writer, {"type": "pong"})

        elif msg["type"] == "pong":
            pass

    def prune_registry(self, depth=1000):
        current_slot = self.chain[-1].slot
        self.slot_registry = {
            k: v for k, v in self.slot_registry.items()
            if k[1] >= current_slot - depth
        }

    async def heartbeat(self):
        while True:
            dead = []
            for peer_id, peer in list(self.peers.items()):
                try:
                    await self.send(peer.writer, {"type": "ping", "version": '1.0', "timestamp": time.time()})
                except:
                    dead.append(peer_id)

            for pid in dead:
                self.peers.pop(pid, None)

            await asyncio.sleep(10)

    async def on_get_block(self, peer_id, msg):
        index = msg["index"]

        if index < 0 or index >= len(self.chain):
            return

        block = self.chain[index]

        await self.send(self.peers[peer_id].writer, {
            "type": "single_block",
            "data": block.to_dict()
        })

    async def on_single_block(self, peer_id, msg):
        incoming_block = Block.from_dict(msg["data"])

        if not self.chain:
            return

        local_block = self.chain[-1]
        prev_block = self.chain[-2] if len(self.chain) > 1 else None

        # Same Index
        if incoming_block.index != local_block.index:
            return

        chain_until_prev = self.chain[:-1] 

        if not self.validator.validate(incoming_block, prev_block, chain_until_prev):
            print("❌ Fork peer invalid → ignoring")
            return


        # Validate my block
        if not self.validator.validate(local_block, prev_block, chain_until_prev):
            print("My block is invalid → rollback")
            self.chain[-1] = incoming_block
            self.storage.save(self.chain)
            return

        # If both valid → it should NOT happen
        print("⚠️ Two valid blocks in the same slot → tie-break")

        if incoming_block.hash < local_block.hash:
            print("Tie-break: peer win")

            # remove old recording
            old_key = (local_block.producer_id, local_block.slot)
            if old_key in self.slot_registry:
                del self.slot_registry[old_key]

            # record new block
            if not self.register_block(incoming_block):
                print("DOUBLE SIGNING DETECTED!")
                return

            self.chain[-1] = incoming_block
            self.storage.save(self.chain)
            self.prune_registry()

        else:
            print("I keep my block")



    async def on_status(self, peer_id, msg):
        peer_index = msg["latest_index"]
        peer_hash = msg.get("latest_hash")

        if self.syncing and self.sync_target and peer_index <= self.sync_target:
            return

        local_index = len(self.chain) - 1
        local_hash = self.chain[-1].hash if self.chain else None

        print(
            f"📊 STATUS from {peer_id}: "
            f"peer=({peer_index}, {peer_hash}) "
            f"local=({local_index}, {local_hash})"
        )

        # Case 0: same state
        if peer_index == local_index and peer_hash == local_hash:
            return

        # Case 1: peer ahead → sync
        if peer_index > local_index:
            self.syncing = True
            self.sync_target = peer_index  
            print("⬇️ I'm behind, I'm asking for blocks")
            await self.send(self.peers[peer_id].writer, {
                "type": "get_blocks",
                "from": local_index + 1
            })
            return


        # Case 2: peer back → ignore
        if peer_index < local_index:
            return

        # Case 3: same index but different hash → fork
        if peer_index == local_index and peer_hash != local_hash:
            print("⚠️ Fork detected, final block comparison")

            await self.send(self.peers[peer_id].writer, {
                "type": "get_block",
                "index": local_index
            })
            return

    async def on_get_blocks(self, peer_id, msg):
        from_index = msg["from"]

        print(f"Sending blocks from index {from_index} to {peer_id}")

        if from_index == 0:
            blocks = self.chain[:]
        else:
            blocks = self.chain[from_index:]

        await self.send(self.peers[peer_id].writer, {
            "type": "blocks",
            "data": [b.to_dict() for b in blocks]
        })

    async def on_blocks(self, peer_id, msg):
        print(f"Received {len(msg['data'])} blocks from {peer_id}")

        for raw in msg["data"]:
            block = Block.from_dict(raw)

            # 🧱 CASE GENESIS
            if not self.chain:
                if block.index != 0:
                    print("❌ Expected genesis, received something else")
                    return

                if not self.validator.validate(block, None, []):
                    print("❌ Invalid genesis")
                    return
                
                # Equivocation check
                if not self.register_block(block):
                    print("❌ DOUBLE SIGNING DETECTED")
                    return

                self.chain.append(block)
                print("🧱 Genesis received and added")
                continue

            chain_until_prev = self.chain[:]
            prev = chain_until_prev[-1]

            if not self.validator.validate(block, prev, chain_until_prev):
                print("❌ Sync failed: invalid block")
                return
            
            if block.prev_hash != prev.hash:
                print("❌ Long fork detected, sync aborted")
                return

            # Equivocation check
            if not self.register_block(block):
                print("❌ DOUBLE SIGNING DETECTED")
                return

            self.chain.append(block)
            
        self.syncing = False
        self.sync_target = None 

        # process blocks arrived during sync
        self.buffered_blocks.sort(key=lambda b: b.index)
        remaining_buffer = []

        for block in self.buffered_blocks:
            local_tip = self.chain[-1].index
            if block.index == local_tip + 1:
                prev = self.chain[-1]
                if self.validator.validate(block, prev, self.chain[:]):
                    self.chain.append(block)
                    included = {tx["txid"] for tx in block.transactions}
                    self.mempool.remove_many(included)
                    print(f"Block #{block.index} added (buffer)")
                else:
                    print(f"❌ Block #{block.index} in invalid buffer, discarded")
            else:
                remaining_buffer.append(block)

        self.buffered_blocks = remaining_buffer

        print("✅ Sync completed")
        self.storage.save(self.chain)
        self.prune_registry()

    async def on_block(self, peer_id, msg):
        block = Block.from_dict(msg["data"])
        local_tip = self.chain[-1].index

        # Old block
        if block.index <= local_tip:
            return

        # Happy Case: Next Block
        if block.index == local_tip + 1:
            chain_until_prev = self.chain[:]  # safe snapshot
            prev = chain_until_prev[-1]

            if not self.validator.validate(block, prev, chain_until_prev):
                print("❌ Live block invalid")
                return

            # Equivocation check
            if not self.register_block(block):
                print("❌ DOUBLE SIGNING DETECTED")
                return

            self.chain.append(block)
            self.storage.save(self.chain)
            self.prune_registry()
            
            # Clean
            included = {tx["txid"] for tx in block.transactions}
            self.mempool.remove_many(included)
            print(f"Block #{block.index} added")
            return

        # Real Gap 
        print(
            f"⚠️ GAP Detected: local={local_tip}, received={block.index}"
        )

        if self.syncing:
            print(f"📦 Buffering block #{block.index} (sync in progress)")
            self.buffered_blocks.append(block)
            return

        self.syncing = True
        await self.send(self.peers[peer_id].writer, {
            "type": "get_blocks",
            "from": local_tip + 1
        })

    async def broadcast_except(self, excluded_peer_id, msg):
        raw = json.dumps(msg).encode()
        header = struct.pack(">I", len(raw))

        dead = []

        for pid, peer in list(self.peers.items()):
            if pid == excluded_peer_id:
                continue
            try:
                peer.writer.write(header + raw)
                await asyncio.wait_for(peer.writer.drain(), timeout=3)
            except Exception:
                dead.append(pid)

        for pid in dead:
            self.peers.pop(pid, None)
