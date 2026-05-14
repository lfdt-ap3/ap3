# AP3 SDK Test Suite

Comprehensive test coverage for the AP3 (Agent Privacy-Preserving Protocol) SDK.

## Overview

The test suite is organized into:

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test complete protocol flows and multi-component interactions

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── unit/                    # Unit tests
│   ├── types/              # Tests for core types and directives
│   ├── services/           # Tests for commitment and discovery services
│   └── operations/         # Tests for PSI operations
└── integration/            # Integration tests
    ├── test_psi_protocol.py          # Complete PSI protocol tests
    └── test_commitments.py           # Commitment chain tests
```

## Running Tests

### Install Test Dependencies

```bash
# Using pip
pip install pytest pytest-asyncio pytest-cov pytest-mock

# Using uv
uv pip install pytest pytest-asyncio pytest-cov pytest-mock
```

### Run All Tests

```bash
pytest
```

### Run Specific Test Categories

```bash
# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# Tests for specific component
pytest tests/unit/types/
pytest tests/unit/services/
pytest tests/unit/operations/
```

### Run Tests by Markers

```bash
# Unit tests only
pytest -m unit

# Integration tests only
pytest -m integration

# Protocol tests (full protocol execution)
pytest -m protocol

# Skip slow tests
pytest -m "not slow"
```

### Run with Coverage

```bash
# Generate coverage report
pytest --cov=src/ap3 --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Run Specific Test Files

```bash
# Test core types
pytest tests/unit/types/test_core.py

# Test directives
pytest tests/unit/types/test_directive.py

# Test commitment manager
pytest tests/unit/services/test_commitment_manager.py

# Test full PSI protocol
pytest tests/integration/test_psi_protocol.py
```

### Run Specific Test Functions

```bash
# Test specific function
pytest tests/unit/types/test_core.py::TestDataSchema::test_create_basic_schema

# Test specific class
pytest tests/integration/test_psi_protocol.py::TestPSIProtocolFullExecution
```

## Test Markers

The test suite uses pytest markers to organize tests:

- `@pytest.mark.unit`: Unit tests for individual components
- `@pytest.mark.integration`: Integration tests for multi-component workflows
- `@pytest.mark.slow`: Tests that take significant time to run
- `@pytest.mark.protocol`: Tests that execute full protocol flows
- `@pytest.mark.requires_network`: Tests that require network access

## Writing Tests

### Using Fixtures

The test suite provides many reusable fixtures in `conftest.py`:

```python
def test_my_feature(sample_data_schema, sample_commitment_metadata):
    """Test using provided fixtures."""
    # Use fixtures directly
    assert sample_data_schema.structure == DataStructure.CUSTOMER_LIST
```

### Available Fixtures

- **Time fixtures**: `current_time`, `future_time`, `past_time`
- **Type fixtures**: `sample_data_schema`, `sample_commitment_metadata`, `sample_structured_commitment`
- **Directive fixtures**: `sample_privacy_intent_directive`, `sample_privacy_result_directive`
- **Mock fixtures**: `mock_httpx_client`, `mock_agent_card`
- **Test data**: `protocol_test_values`, `psi_test_data`

### Test Examples

#### Unit Test Example

```python
@pytest.mark.unit
def test_commitment_metadata_validation(sample_commitment_metadata):
    """Test CommitmentMetadata validation."""
    assert sample_commitment_metadata.validate_metadata() == True
```

#### Integration Test Example

```python
@pytest.mark.integration
@pytest.mark.protocol
def test_full_protocol(protocol_test_values):
    """Test complete PSI protocol."""
    op = PSIOperation()
    # Execute initiator/receiver rounds...
```

## Test Coverage Goals

The test suite aims for:

- **Unit Test Coverage**: >90% for core types, services, and operations
- **Integration Test Coverage**: Complete protocol flows, error handling
- **Protocol Correctness**: Verify cryptographic protocols produce correct results

## Continuous Integration

Tests are designed to run in CI/CD pipelines. Use markers to control which tests run:

```bash
# Fast tests only (skip slow tests)
pytest -m "not slow"

# All tests except network-dependent
pytest -m "not requires_network"
```

## Troubleshooting

### Async Test Failures

If async tests fail, ensure `pytest-asyncio` is installed:

```bash
pip install pytest-asyncio
```

### Import Errors

Ensure the AP3 SDK is installed in development mode:

```bash
pip install -e .
```

## Contributing

When adding new features:

1. **Write unit tests** for new functions/classes
2. **Write integration tests** for new protocols or workflows
3. **Use appropriate markers** to categorize tests
4. **Add fixtures** to `conftest.py` for reusable test data
5. **Update this README** if adding new test categories

## Test Performance

Typical test execution times:

- Unit tests: ~5-10 seconds
- Integration tests: ~5-10 seconds
- Full suite: ~1-2 minutes

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
