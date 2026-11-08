from ai_runtime import PROFILES, acquire, release, busy
assert [(x,PROFILES[x]['budget_gb']) for x in PROFILES] == [('Eco',2),('Balanced',4),('Accelerated',8)]
assert acquire('analysis')
assert busy()
assert not acquire('chat')
release('analysis')
assert not busy()
assert acquire('chat')
release('chat')
from ollama_memory import release_models
assert release_models([]) == {}
print('Basic Beta.3 coordination tests passed')
