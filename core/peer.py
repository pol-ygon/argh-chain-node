# core/peer.py

class Peer:
    def __init__(self, node_id: str, writer):
        self.node_id = node_id
        self.writer = writer
