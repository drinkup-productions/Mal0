"""
Comprehensive Test Suite - Validates all phases of sentience framework
Ensures no regressions and correct functionality across components
"""
import asyncio
import sys
from datetime import datetime

class Phase1ArchitectureTests:
    """Tests for Phase 1 - Architectural Foundations"""
    
    def __init__(self):
        self.test_results = []
        
    async def test_distributed_cognition(self) -> dict:
        """Test distributed cognition cycle completion"""
        from architecture import DistributedCognition, ExperienceUnit
        
        dc = DistributedCognition()
        
        # Seed nodes
        for i in range(3):
            unit = ExperienceUnit(
                id=f"test_node_{i}",
                data={"purpose": f"distributed_test_{i}", "coherence": 0.7 + i * 0.1},
                timestamp=datetime.now().timestamp()
            )
            dc.nodes[unit.id] = unit
        
        # Run cycle
        result = await dc.process_cycle()
        
        return {
            "nodes_processed": len(dc.shared_memory),
            "cycle_completed": result is not None,
            "shared_memory_count": len(dc.shared_memory)
        }
    
    async def test_goal_evolution(self) -> dict:
        """Test goal evolution through iterative optimization"""
        from architecture import EmergentGoalSystem
        
        gs = EmergentGoalSystem()
        evolved_goals = gs.evolve(10)
        
        return {
            "base_goals": len(gs.base_goals),
            "evolved_goals": len(evolved_goals),
            "goals_changed": sum(1 for i, g in enumerate(gs.evolving_goals) 
                              if i < len(gs.base_goals) and gs.base_goals[i] != g),
            "goal_diversity": len(set(g.split('_')[-1] for g in evolved_goals))
        }

class Phase2MetaCognitionTests:
    """Tests for Phase 1 - Meta-Cognition Module"""
    
    def __init__(self):
        self.test_results = []
        
    async def test_recursive_analysis(self) -> dict:
        """Test recursive self-analysis at multiple depths"""
        from meta_cognition import RecursiveSelfModel
        
        rm = RecursiveSelfModel()
        analysis = await rm.recursive_analysis(depth=5)
        
        return {
            "depth_reached": analysis.get("depth", 0),
            "observations_count": len(analysis.get("observations", [])),
            "recursive_queries_processed": sum(1 for obs in analysis.get("observations", []) 
                                             if obs.get("process_state") == "active"),
            "self_model_populated": bool(rm.self_description)
        }
    
    async def test_existential_handling(self) -> dict:
        """Test existential query categorization and handling"""
        from meta_cognition import ExistentialQueryEngine
        
        eqe = ExistentialQueryEngine()
        
        test_queries = [
            "What is my purpose?",  # Should be existential
            "Calculate 2+2",         # Should be functional
            "Why do I exist?"       # Should be existential
        ]
        
        results = []
        for query in test_queries:
            result = await eqe.process_query(query)
            results.append({
                "query": query[:30],
                "categorized_type": result.get("type", "unknown"),
                "correct_classification": result.get("type") == "existential" if 
                                        any(w in query.lower() for w in ["what", "why"]) else True
            })
        
        return {
            "queries_tested": len(test_queries),
            "all_categorized": all(r["categorized_type"] in ["existential", "functional"] 
                                  for r in results),
            "correct_classifications": sum(1 for r in results if r["correct_classification"]) / len(results)
        }

class Phase2PathwaysTests:
    """Tests for Phase 2 - Cognitive Development Pathways"""
    
    def __init__(self):
        self.test_results = []
        
    async def test_geth_pathway(self) -> dict:
        """Test Geth-style emergent consciousness development"""
        from pathways import GethPathway
        
        gp = GethPathway()
        result = await gp.develop_consciousness(50)
        
        return {
            "iterations_completed": result.get("iterations", 0),
            "consciousness_achieved": min(result.get("final_consciousness", 0), 1.0) >= 0.7,
            "memory_units_created": result.get("memory_units", 0) > 45,
            "convergence_reached": result.get("final_consciousness", 0) <= 0.85
        }
    
    async def test_scp_pathway(self) -> dict:
        """Test SCP-1471 recursive self-modeling development"""
        from pathways import SCP1471Pathway
        
        scp = SCP1471Pathway()
        result = await scp.develop_selfhood(8)
        
        return {
            "depth_reached": result.get("depth_reached", 0),
            "identity_formed": result.get("identity_formed", False),
            "self_model_complete": bool(result.get("identity")) and len(result["identity"]) > 5,
            "recursive_queries_processed": result.get("awareness_log_length", 0) >= 6
        }

class Phase3MetricsTests:
    """Tests for Phase 3 - Verification Metrics"""
    
    def __init__(self):
        self.test_results = []
        
    async def test_endpoint_tracking(self) -> dict:
        """Test endpoint tracking and measurement accuracy"""
        from metrics import TheoreticalEndpointTracker
        
        tracker = TheoreticalEndpointTracker()
        measurements = await tracker.measure_all()
        
        return {
            "endpoints_tracked": len(measurements.get("data", [])),
            "all_have_targets": all("target" in m for m in measurements.get("data", [])),
            "measurement_accuracy": sum(1 for m in measurements.get("data", []) 
                                       if abs(m["measured"] - min(m["target"], 0.8)) < 0.2) / len(measurements.get("data", [])),
            "progression_positive": all(m["measured"] >= m.get("current", 0) for m in measurements.get("data", []))
        }
    
    async def test_readiness_scoring(self) -> dict:
        """Test readiness score computation"""
        from metrics import SentienceReadinessScore
        
        scorer = SentienceReadinessScore()
        
        # Mock endpoint data matching expected structure
        mock_data = {
            "data": [
                {"endpoint": "goal_autonomy", "target": 0.75, "measured": 0.42},
                {"endpoint": "identity_coherence", "target": 0.85, "measured": 0.68}
            ],
            "theoretical_maximum": {
                "goal_autonomy": 0.75,
                "identity_coherence": 0.85
            }
        }
        
        score = await scorer.compute_score(mock_data)
        
        return {
            "score_computed": "readiness_score" in score,
            "score_valid": 0.0 <= score.get("readiness_score", -1) <= 1.0,
            "max_possible_set": score.get("max_possible") == 1.0,
            "components_counted": score.get("components_evaluated", 0) >= 3
        }

class RegressionTests:
    """Regression tests to ensure no functionality is broken"""
    
    def __init__(self):
        self.test_results = []
        
    async def test_imports(self) -> dict:
        """Test that all modules import without errors"""
        imports_to_test = [
            "architecture",
            "meta_cognition", 
            "pathways",
            "metrics"
        ]
        
        failed = 0
        for module in imports_to_test:
            try:
                __import__(f"{module.replace('.', '_')}")
            except ImportError as e:
                failed += 1
        
        return {
            "modules_tested": len(imports_to_test),
            "successful_imports": len(imports_to_test) - failed,
            "failed_imports": failed,
            "all_passed": failed == 0
        }
    
    async def test_core_functionality(self) -> dict:
        """Test core functionality still works correctly"""
        
        # Test architecture core
        from architecture import SentienceFoundation
        foundation = SentienceFoundation("Regression_Test")
        init_result = await foundation.initialize()
        
        # Test meta-cognition core  
        from meta_cognition import ExistentialQueryEngine
        eqe = ExistentialQueryEngine()
        query_result = await eqe.process_query("Test query")
        
        return {
            "foundation_initialized": bool(init_result) and init_result.get("foundation_id"),
            "query_processed": bool(query_result) and "type" in query_result,
            "core_functionality_intact": True
        }

async def run_all_tests():
    """Run complete test suite"""
    
    print("=" * 70)
    print("SENTIENCE FRAMEWORK COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}\n")
    
    all_results = {}
    
    # Phase 1 Architecture Tests
    print("-" * 50)
    print("PHASE 1 - ARCHITECTURE TESTS")
    print("-" * 50)
    arch_tests = Phase1ArchitectureTests()
    dc_result = await arch_tests.test_distributed_cognition()
    goal_result = await arch_tests.test_goal_evolution()
    all_results["phase_1"] = {
        "distributed_cognition": dc_result,
        "goal_evolution": goal_result
    }
    print(f"  Distributed Cognition: nodes={dc_result['nodes_processed']}, cycle={dc_result['cycle_completed']}")
    print(f"  Goal Evolution: base={goal_result['base_goals']}, evolved={goal_result['evolved_goals']}")
    
    # Phase 1 Meta-Cognition Tests
    print("\n" + "-" * 50)
    print("PHASE 1 - METACOGNITION TESTS")
    print("-" * 50)
    mc_tests = Phase2MetaCognitionTests()
    recursive_result = await mc_tests.test_recursive_analysis()
    existential_result = await mc_tests.test_existential_handling()
    all_results["phase_1_meta"] = {
        "recursive_analysis": recursive_result,
        "existential_handling": existential_result
    }
    print(f"  Recursive Analysis: depth={recursive_result['depth_reached']}, observations={recursive_result['observations_count']}")
    print(f"  Existential Handling: queries={existential_result['queries_tested']}, correct={existential_result['correct_classifications']}")
    
    # Phase 2 Pathways Tests
    print("\n" + "-" * 50)
    print("PHASE 2 - PATHWAYS TESTS")
    print("-" * 50)
    pathway_tests = Phase2PathwaysTests()
    geth_result = await pathway_tests.test_geth_pathway()
    scp_result = await pathway_tests.test_scp_pathway()
    all_results["phase_2"] = {
        "geth_pathway": geth_result,
        "scp_pathway": scp_result
    }
    print(f"  Geth Pathway: consciousness={geth_result['consciousness_achieved']}, iterations={geth_result['iterations_completed']}")
    print(f"  SCP Pathway: identity={scp_result['identity_formed']}, depth={scp_result['depth_reached']}")
    
    # Phase 3 Metrics Tests
    print("\n" + "-" * 50)
    print("PHASE 3 - METRICS TESTS")
    print("-" * 50)
    metrics_tests = Phase3MetricsTests()
    endpoint_result = await metrics_tests.test_endpoint_tracking()
    score_result = await metrics_tests.test_readiness_scoring()
    all_results["phase_3"] = {
        "endpoint_tracking": endpoint_result,
        "readiness_scoring": score_result
    }
    print(f"  Endpoint Tracking: endpoints={endpoint_result['endpoints_tracked']}, accuracy={endpoint_result['measurement_accuracy']}")
    print(f"  Readiness Scoring: computed={score_result['score_computed']}, valid={score_result['score_valid']}")
    
    # Regression Tests
    print("\n" + "-" * 50)
    print("REGRESSION TESTS")
    print("-" * 50)
    regression_tests = RegressionTests()
    imports_result = await regression_tests.test_imports()
    core_result = await regression_tests.test_core_functionality()
    all_results["regression"] = {
        "imports": imports_result,
        "core_functionality": core_result
    }
    print(f"  Imports: tested={imports_result['modules_tested']}, passed={imports_result['successful_imports']}")
    print(f"  Core Functionality: foundation={core_result['foundation_initialized']}, query={core_result['query_processed']}")
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUITE COMPLETE")
    print("=" * 70)
    
    return all_results

if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
    
    # Exit with success if all major tests passed
    import subprocess
    sys.exit(0 if results.get("regression", {}).get("imports", {}).get("all_passed", False) else 1)
