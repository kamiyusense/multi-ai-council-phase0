class CoreProviderAdapter:
    def prepare(self, case_context):
        pass
    def preflight(self, prepared_context):
        pass
    def dispatch(self, prepared_context):
        pass
    def collect(self, process_handle):
        pass
    def abort(self, process_handle):
        pass
    def classify(self, raw_result):
        pass
