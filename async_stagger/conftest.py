import asyncio

import pytest


# Find all available event loop policies in asyncio, and in uvloop if installed
available_policies = {
    getattr(asyncio, p)
    for p in dir(asyncio)
    if p.endswith('EventLoopPolicy')
    and not p.startswith('Abstract')
}

try:
    import uvloop

    # Give uvloop's policy a more recognizable name
    class UvloopEventLoopPolicy(uvloop.EventLoopPolicy):
        pass

    available_policies.add(UvloopEventLoopPolicy)
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
    available_policies.update(eager_policies)


# Run each test with each policy
@pytest.fixture(params=available_policies)
def event_loop_policy(request):
    return request.param()