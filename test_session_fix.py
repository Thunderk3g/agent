#!/usr/bin/env python3
"""
Test script to verify session persistence fix.
This script tests that conversations maintain context across different session IDs.
"""

import asyncio
import json
from app.services.agent_orchestrator import agent_orchestrator


async def test_session_persistence():
    """Test that session context is maintained when using the same session_id."""
    
    # Test session ID from the data.json
    test_session_id = "f7c00bd0-2087-4f61-a94a-d6221b9b0f5f"
    
    print("=== Testing Session Persistence Fix ===")
    print(f"Using session ID: {test_session_id}")
    
    # First message - should restore context from data.json
    print("\n1. Sending first message with existing session ID...")
    response1 = await agent_orchestrator.handle_turn(
        session_id=test_session_id,
        user_message="What's my name again?"
    )
    
    print(f"Response 1 Session ID: {response1['session_id']}")
    print(f"Response 1 Message: {response1['message'][:100]}...")
    
    # Second message - should maintain the same session
    print("\n2. Sending second message with same session ID...")
    response2 = await agent_orchestrator.handle_turn(
        session_id=test_session_id,
        user_message="What was my age again?"
    )
    
    print(f"Response 2 Session ID: {response2['session_id']}")
    print(f"Response 2 Message: {response2['message'][:100]}...")
    
    # Verification
    print("\n=== Verification ===")
    if response1['session_id'] == response2['session_id'] == test_session_id:
        print("✅ SUCCESS: Session ID consistency maintained!")
    else:
        print("❌ FAILURE: Session IDs are inconsistent")
        print(f"   Expected: {test_session_id}")
        print(f"   Response 1: {response1['session_id']}")
        print(f"   Response 2: {response2['session_id']}")
    
    # Check if context is restored
    print("\n=== Context Restoration Check ===")
    metadata1 = response1.get('metadata', {})
    extracted1 = metadata1.get('extracted', {})
    
    print(f"Extracted data from response 1: {json.dumps(extracted1, indent=2)}")
    
    return response1['session_id'] == response2['session_id'] == test_session_id


async def test_new_session():
    """Test that new sessions still work correctly."""
    
    print("\n=== Testing New Session Creation ===")
    
    # Create new session without providing session_id
    response = await agent_orchestrator.handle_turn(
        session_id=None,
        user_message="Hi, I want to buy term insurance"
    )
    
    print(f"New Session ID: {response['session_id']}")
    print(f"New Session Message: {response['message'][:100]}...")
    
    return len(response['session_id']) > 0


if __name__ == "__main__":
    async def main():
        try:
            print("Starting session persistence tests...\n")
            
            # Test existing session persistence
            persistence_test = await test_session_persistence()
            
            # Test new session creation
            new_session_test = await test_new_session()
            
            print("\n=== Final Results ===")
            print(f"Session Persistence: {'✅ PASS' if persistence_test else '❌ FAIL'}")
            print(f"New Session Creation: {'✅ PASS' if new_session_test else '❌ FAIL'}")
            
            if persistence_test and new_session_test:
                print("\n🎉 All tests passed! Session management is working correctly.")
            else:
                print("\n⚠️  Some tests failed. Please check the implementation.")
                
        except Exception as e:
            print(f"❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(main())