import sqlite3
import uuid
from datetime import date, timedelta
from pathlib import Path


class Store:
    def __init__(self, path, today=None):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.today = today or date.today()
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, item TEXT NOT NULL, amount_paise INTEGER NOT NULL,
                status TEXT NOT NULL, delivered TEXT, refundable INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, order_id TEXT UNIQUE NOT NULL REFERENCES orders(id),
                reason TEXT NOT NULL, amount_paise INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','approved','denied')));
            CREATE TABLE IF NOT EXISTS refunds (
                order_id TEXT PRIMARY KEY REFERENCES orders(id),
                request_id TEXT UNIQUE NOT NULL REFERENCES requests(id), amount_paise INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, interaction_id TEXT);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, at TEXT DEFAULT CURRENT_TIMESTAMP,
                session_id TEXT, tool TEXT, outcome TEXT);
        """)

    def close(self):
        self.db.close()

    def seed(self):
        rows = [
            ('ORD-1001', 'Headphones', 249900, 'delivered', 5, 1),
            ('ORD-1002', 'Keyboard', 399900, 'delivered', 45, 1),
            ('ORD-1003', 'Digital gift card', 100000, 'delivered', 2, 0),
            ('ORD-1004', 'Mouse', 129900, 'shipped', None, 1),
            ('ORD-1005', 'Webcam', 199900, 'delivered', 30, 1),
        ]
        with self.db:
            for oid, item, amount, status, days, refundable in rows:
                delivered = (self.today - timedelta(days=days)).isoformat() if days is not None else None
                self.db.execute('INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?,?)',
                                (oid, item, amount, status, delivered, refundable))
        return {'seeded': True, 'note': 'Existing orders are preserved; dates are relative to first seed.'}

    def order(self, order_id):
        row = self.db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if row is None:
            raise ValueError('Order not found')
        return dict(row)

    def eligibility(self, order_id):
        order = self.order(order_id)
        age = (self.today - date.fromisoformat(order['delivered'])).days if order['delivered'] else None
        refunded = self.db.execute('SELECT 1 FROM refunds WHERE order_id=?', (order_id,)).fetchone()
        reason = ('Already refunded' if refunded else
                  'Order is not delivered' if order['status'] != 'delivered' else
                  'Item is non-refundable' if not order['refundable'] else
                  'Outside the 30-day window' if age is None or not 0 <= age <= 30 else 'Eligible')
        return {'order_id': order_id, 'eligible': reason == 'Eligible', 'reason': reason,
                'amount_paise': order['amount_paise'], 'currency': 'INR', 'days_since_delivery': age}

    def prepare(self, order_id, reason):
        # A write lock makes policy check + duplicate check + insertion atomic.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            policy = self.eligibility(order_id)
            if not policy['eligible']:
                raise ValueError(policy['reason'])
            existing = self.db.execute('SELECT * FROM requests WHERE order_id=?', (order_id,)).fetchone()
            if existing:
                return dict(existing)
            rid = 'REF-' + uuid.uuid4().hex[:12]
            self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?)',
                            (rid, order_id, reason, policy['amount_paise'], 'pending'))
            return self.request(rid)

    def request(self, request_id):
        row = self.db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if row is None:
            raise ValueError('Refund request not found')
        return dict(row)

    def decide(self, request_id, approve):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            request = self.request(request_id)
            if request['state'] != 'pending':
                return request
            if approve:
                policy = self.eligibility(request['order_id'])
                if not policy['eligible'] or policy['amount_paise'] != request['amount_paise']:
                    raise ValueError('Approval blocked: eligibility or amount changed')
                self.db.execute('INSERT INTO refunds VALUES (?,?,?)',
                                (request['order_id'], request_id, request['amount_paise']))
            self.db.execute('UPDATE requests SET state=? WHERE id=?',
                            ('approved' if approve else 'denied', request_id))
            return self.request(request_id)

    def previous(self, session):
        row = self.db.execute('SELECT interaction_id FROM sessions WHERE id=?', (session,)).fetchone()
        return row[0] if row else None

    def remember(self, session, interaction_id):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)', (session, interaction_id))

    def event(self, session, tool, outcome):
        with self.db:
            self.db.execute('INSERT INTO events(session_id,tool,outcome) VALUES (?,?,?)',
                            (session, tool, outcome))
