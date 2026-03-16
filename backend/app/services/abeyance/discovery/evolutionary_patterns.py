"""
Evolutionary Patterns — Layer 5, Mechanism #14 (LLD v3.0 §10.4).

Genetic algorithm-based exploration of mask/weight pattern space.
Evolves populations of pattern individuals per failure mode.
"""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.abeyance_v3_orm import (
    PatternIndividualORM,
    PatternIndividualArchiveORM,
    EvolutionGenerationLogORM,
    EvolutionPartitionStateORM,
)

logger = logging.getLogger(__name__)

POPULATION_SIZE = 20
TOURNAMENT_K = 3
MUTATION_RATE = 0.15
RECOMBINATION_RATE = 0.30
ELITISM_COUNT = 2
MAX_GENERATIONS = 100

# Fitness weights
W_PREDICTIVE = 0.4
W_NOVELTY = 0.3
W_COMPRESSION = 0.3


class EvolutionaryPatternService:
    """Genetic algorithm exploration of mask/weight pattern space."""

    async def evolve_generation(
        self,
        session: AsyncSession,
        tenant_id: str,
        failure_mode_profile: str,
        predictive_scores: Optional[dict[str, float]] = None,
    ) -> dict:
        """Run one generation of the evolutionary algorithm."""
        state = await self._get_or_create_state(session, tenant_id, failure_mode_profile)

        if state.current_generation >= MAX_GENERATIONS:
            return {"status": "MAX_GENERATIONS_REACHED"}

        # Load current population
        pop_stmt = (
            select(PatternIndividualORM)
            .where(
                PatternIndividualORM.tenant_id == tenant_id,
                PatternIndividualORM.failure_mode_profile == failure_mode_profile,
            )
            .order_by(PatternIndividualORM.fitness.desc())
        )
        pop_result = await session.execute(pop_stmt)
        population = list(pop_result.scalars().all())

        # Initialize population if empty
        if not population:
            population = await self._initialize_population(
                session, tenant_id, failure_mode_profile,
            )

        # Evaluate fitness
        for ind in population:
            ind.fitness = self._evaluate_fitness(ind, predictive_scores)

        # Sort by fitness
        population.sort(key=lambda x: x.fitness, reverse=True)

        # Archive elites
        for ind in population[:ELITISM_COUNT]:
            archive = PatternIndividualArchiveORM(
                id=uuid4(),
                tenant_id=tenant_id,
                failure_mode_profile=failure_mode_profile,
                pattern_string=ind.pattern_string,
                fitness=ind.fitness,
                predictive_power=ind.predictive_power,
                novelty=ind.novelty,
                compression_gain=ind.compression_gain,
                generation=state.current_generation,
            )
            session.add(archive)

        # Selection + crossover + mutation
        new_generation = []
        mutations = 0
        recombinations = 0

        # Keep elites
        for ind in population[:ELITISM_COUNT]:
            new_generation.append(ind.pattern_string)

        # Fill rest via tournament selection + crossover
        while len(new_generation) < POPULATION_SIZE:
            parent_a = self._tournament_select(population)
            parent_b = self._tournament_select(population)

            if random.random() < RECOMBINATION_RATE:
                child = self._crossover(parent_a.pattern_string, parent_b.pattern_string)
                recombinations += 1
            else:
                child = parent_a.pattern_string

            if random.random() < MUTATION_RATE:
                child = self._mutate(child)
                mutations += 1

            new_generation.append(child)

        # Replace population
        await session.execute(
            delete(PatternIndividualORM).where(
                PatternIndividualORM.tenant_id == tenant_id,
                PatternIndividualORM.failure_mode_profile == failure_mode_profile,
            )
        )

        for pattern_str in new_generation:
            ind = PatternIndividualORM(
                id=uuid4(),
                tenant_id=tenant_id,
                failure_mode_profile=failure_mode_profile,
                pattern_string=pattern_str,
                generation=state.current_generation + 1,
            )
            session.add(ind)

        # Log generation
        mean_fitness = sum(p.fitness for p in population) / max(len(population), 1)
        max_fitness = population[0].fitness if population else 0.0

        gen_log = EvolutionGenerationLogORM(
            id=uuid4(),
            tenant_id=tenant_id,
            failure_mode_profile=failure_mode_profile,
            generation=state.current_generation + 1,
            population_size=len(new_generation),
            mean_fitness=round(mean_fitness, 4),
            max_fitness=round(max_fitness, 4),
            mutations=mutations,
            recombinations=recombinations,
            selections=POPULATION_SIZE - ELITISM_COUNT,
        )
        session.add(gen_log)

        state.current_generation += 1
        state.last_evolved_at = datetime.now(timezone.utc)

        await session.flush()
        logger.info(
            "Evolution gen %d: tenant=%s profile=%s mean=%.4f max=%.4f",
            state.current_generation, tenant_id, failure_mode_profile,
            mean_fitness, max_fitness,
        )
        return {
            "generation": state.current_generation,
            "mean_fitness": round(mean_fitness, 4),
            "max_fitness": round(max_fitness, 4),
            "mutations": mutations,
            "recombinations": recombinations,
        }

    async def _initialize_population(
        self,
        session: AsyncSession,
        tenant_id: str,
        failure_mode_profile: str,
    ) -> list[PatternIndividualORM]:
        """Create initial random population."""
        population = []
        for _ in range(POPULATION_SIZE):
            pattern = self._random_pattern()
            ind = PatternIndividualORM(
                id=uuid4(),
                tenant_id=tenant_id,
                failure_mode_profile=failure_mode_profile,
                pattern_string=pattern,
                generation=0,
            )
            session.add(ind)
            population.append(ind)
        await session.flush()
        return population

    @staticmethod
    def _random_pattern() -> str:
        """Generate a random 4-char mask pattern (S=semantic, T=topo, O=oper, +/-)."""
        chars = "STO"
        length = random.randint(1, 3)
        selected = random.sample(chars, length)
        return "".join(sorted(selected))

    @staticmethod
    def _evaluate_fitness(
        ind: PatternIndividualORM,
        predictive_scores: Optional[dict[str, float]] = None,
    ) -> float:
        """Evaluate fitness as weighted combination of objectives."""
        predictive = ind.predictive_power
        if predictive_scores and ind.pattern_string in predictive_scores:
            predictive = predictive_scores[ind.pattern_string]
            ind.predictive_power = predictive

        fitness = (
            W_PREDICTIVE * predictive
            + W_NOVELTY * ind.novelty
            + W_COMPRESSION * ind.compression_gain
        )
        return max(0.0, min(1.0, fitness))

    @staticmethod
    def _tournament_select(population: list[PatternIndividualORM]) -> PatternIndividualORM:
        """Tournament selection."""
        competitors = random.sample(population, min(TOURNAMENT_K, len(population)))
        return max(competitors, key=lambda x: x.fitness)

    @staticmethod
    def _crossover(a: str, b: str) -> str:
        """Single-point crossover of pattern strings."""
        all_chars = set(a) | set(b)
        midpoint = len(all_chars) // 2
        chars_list = sorted(all_chars)
        child_chars = chars_list[:midpoint] + [c for c in b if c in chars_list[midpoint:]]
        return "".join(sorted(set(child_chars))) or "S"

    @staticmethod
    def _mutate(pattern: str) -> str:
        """Flip one character in the pattern."""
        chars = list(pattern)
        all_options = ["S", "T", "O"]
        if random.random() < 0.5 and len(chars) < 3:
            # Add a character
            available = [c for c in all_options if c not in chars]
            if available:
                chars.append(random.choice(available))
        elif len(chars) > 1:
            # Remove a character
            chars.pop(random.randint(0, len(chars) - 1))
        return "".join(sorted(set(chars))) or "S"

    async def _get_or_create_state(
        self, session: AsyncSession, tenant_id: str, profile: str,
    ) -> EvolutionPartitionStateORM:
        stmt = select(EvolutionPartitionStateORM).where(
            EvolutionPartitionStateORM.tenant_id == tenant_id,
            EvolutionPartitionStateORM.failure_mode_profile == profile,
        )
        result = await session.execute(stmt)
        state = result.scalar_one_or_none()
        if state is None:
            state = EvolutionPartitionStateORM(
                tenant_id=tenant_id,
                failure_mode_profile=profile,
                current_generation=0,
            )
            session.add(state)
            await session.flush()
        return state
