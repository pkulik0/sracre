class Api:
    class Entry:
        def __init__(self, api_name, key, quota_used, quota_total, reset_time):
            self.api_name = api_name
            self.key = key
            self.quota_used = quota_used
            self.quota_total = quota_total
            self.reset_time = reset_time

    def __init__(self, api_name, db):
        self.db = db
        self.cursor = db.cursor()
        self.api_name = api_name

    def get_key(self, quota_needed):
        return Api.Entry(*self.cursor.execute("SELECT api, key, quota_used, quota_total, reset_time FROM keys "
                                              "WHERE api = ? AND quota_total - quota_used >= ? ORDER BY "
                                              "quota_used LIMIT 1", (self.api_name, quota_needed)).fetchone())

    def add_key(self, key, quota):
        self.cursor.execute("INSERT INTO keys (api, key, quota_used, quota_total, reset_time) VALUES (?, ?, ?, ?, ?)",
                            (self.api_name, key, 0, quota, 0))
        self.db.commit()

    def incr_key_quota(self, key, quota):
        self.cursor.execute("UPDATE keys SET quota_used = quota_used + ? WHERE key = ?", (quota, key))
        self.db.commit()

    def get_all_keys(self):
        return [Api.Entry(*row) for row in self.cursor.execute("SELECT api, key, quota_used, quota_total, "
                                                               "reset_time FROM keys WHERE api = ?",
                                                               (self.api_name,)).fetchall()]
