
class AWENATING:
    def validate(self, query):
        if "hack" in query.lower():
            raise Exception("Blocked")

    def enforce(self, output):
        return {"verified": True, "output": output}
