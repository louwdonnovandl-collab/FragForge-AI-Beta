from ai_runtime import MemoryBudgetGuard, PROFILES
from local_director import clean_reply
assert clean_reply('internal reasoning\n</think>\n\nFull answer\nSecond paragraph') == 'Full answer\nSecond paragraph'
assert clean_reply('<think>internal</think>Visible') == 'Visible'
for profile,budget in [('Eco',2),('Balanced',4),('Accelerated',8)]:
    clock=[0.0]
    guard=MemoryBudgetGuard(profile,clock=lambda:clock[0])
    assert abs(guard.ceiling_gb-budget*1.1)<1e-8
    assert guard.check(budget*1.05) is None
    assert guard.check(budget*1.11) is None
    clock[0]=4.9
    assert guard.check(budget*1.11) is None
    clock[0]=5.1
    assert guard.check(budget*1.11)
    assert guard.check(budget) is None
    clock[0]=10
    assert guard.check(budget*1.11) is None
print('FF_050 Beta.4 memory and reasoning tests passed')
