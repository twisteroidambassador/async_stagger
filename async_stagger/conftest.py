import asyncio

import pytest


# Find all available event loop policies in asyncio, and in uvloop if installed
available_policies = [
    getattr(asyncio, p)
    for p in dir(asyncio)
    if p.endswith('EventLoopPolicy')
    and not p.startswith('Abstract')
]

if len(available_policies) > 1:
    # If there's more than one policies, then it must have one default and at least two named policies
    assert len(available_policies) > 2
    available_policies.remove('DefaultEventLoopPolicy')

try:
    import uvloop

    # Give uvloop's policy a more recognizable name
    class UvloopEventLoopPolicy(uvloop.EventLoopPolicy):
        pass

    available_policies.append(UvloopEventLoopPolicy)
except ImportError:
    pass


if hasattr(asyncio, 'eager_task_factory'):
    # Create a new version of each available policy that uses eager task factory
    def create_eager_policy(policy: asyncio.AbstractEventLoopPolicy) -> asyncio.AbstractEventLoopPolicy:
        class NewEagerPolicy(policy):
            def new_event_loop(self):
                loop = super().new_event_loop()
                loop.set_task_factory(asyncio.eager_task_factory)
                return loop
        
        NewEagerPolicy.__name__ = f'Eager{policy.__name__}'
        
        return NewEagerPolicy


    eager_policies = []
    for policy in available_policies:
        eager_policies.append(create_eager_policy(policy))
    available_policies.extend(eager_policies)


# Run each test with each policy
@pytest.fixture(params=available_policies)
def event_loop_policy(request):
    return request.param()