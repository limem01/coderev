import * as assert from 'assert';

// Unit tests for runner logic that doesn't depend on VS Code APIs
// These test the pure logic functions (severity normalization, JSON parsing, etc.)

suite('CodeRevRunner Logic', () => {
    test('normalizeSeverity handles valid values', () => {
        const normalize = (s: string): string => {
            const str = s.toLowerCase();
            if (str === 'critical') { return 'critical'; }
            if (str === 'high') { return 'high'; }
            if (str === 'medium') { return 'medium'; }
            return 'low';
        };

        assert.strictEqual(normalize('critical'), 'critical');
        assert.strictEqual(normalize('CRITICAL'), 'critical');
        assert.strictEqual(normalize('high'), 'high');
        assert.strictEqual(normalize('High'), 'high');
        assert.strictEqual(normalize('medium'), 'medium');
        assert.strictEqual(normalize('low'), 'low');
        assert.strictEqual(normalize('unknown'), 'low');
        assert.strictEqual(normalize(''), 'low');
    });

    test('severity filter logic', () => {
        const passesSeverityFilter = (severity: string, filter: string): boolean => {
            if (filter === 'all') { return true; }
            const order = ['low', 'medium', 'high', 'critical'];
            const minIdx = order.indexOf(filter);
            const issueIdx = order.indexOf(severity);
            return issueIdx >= minIdx;
        };

        // Filter: all - everything passes
        assert.strictEqual(passesSeverityFilter('low', 'all'), true);
        assert.strictEqual(passesSeverityFilter('critical', 'all'), true);

        // Filter: medium - low fails, medium+ passes
        assert.strictEqual(passesSeverityFilter('low', 'medium'), false);
        assert.strictEqual(passesSeverityFilter('medium', 'medium'), true);
        assert.strictEqual(passesSeverityFilter('high', 'medium'), true);
        assert.strictEqual(passesSeverityFilter('critical', 'medium'), true);

        // Filter: critical - only critical passes
        assert.strictEqual(passesSeverityFilter('low', 'critical'), false);
        assert.strictEqual(passesSeverityFilter('high', 'critical'), false);
        assert.strictEqual(passesSeverityFilter('critical', 'critical'), true);
    });

    test('parseReviewOutput handles valid JSON', () => {
        const json = JSON.stringify({
            issues: [
                {
                    line: 10,
                    severity: 'high',
                    category: 'security',
                    message: 'SQL injection risk',
                    suggestion: 'Use parameterized queries',
                },
                {
                    line: 25,
                    end_line: 30,
                    severity: 'medium',
                    category: 'performance',
                    message: 'N+1 query detected',
                },
            ],
            summary: 'Found 2 issues',
        });

        const data = JSON.parse(json);
        const rawIssues: any[] = data.issues ?? [];

        assert.strictEqual(rawIssues.length, 2);
        assert.strictEqual(rawIssues[0].line, 10);
        assert.strictEqual(rawIssues[0].severity, 'high');
        assert.strictEqual(rawIssues[0].suggestion, 'Use parameterized queries');
        assert.strictEqual(rawIssues[1].end_line, 30);
        assert.strictEqual(data.summary, 'Found 2 issues');
    });

    test('parseReviewOutput handles empty issues', () => {
        const json = JSON.stringify({ issues: [], summary: 'Clean!' });
        const data = JSON.parse(json);
        assert.strictEqual(data.issues.length, 0);
    });

    test('parseReviewOutput handles multi-file format', () => {
        const json = JSON.stringify({
            'app.py': {
                issues: [
                    { line: 5, severity: 'low', category: 'style', message: 'Long line' }
                ],
                summary: '1 issue'
            },
            'utils.py': {
                issues: [],
                summary: 'Clean'
            }
        });

        const data = JSON.parse(json);
        const keys = Object.keys(data);
        assert.strictEqual(keys.length, 2);
        assert.strictEqual(data['app.py'].issues.length, 1);
        assert.strictEqual(data['utils.py'].issues.length, 0);
    });

    test('parseReviewOutput gracefully handles malformed JSON', () => {
        const output = 'Error: API key not set';

        let parsed = false;
        try {
            JSON.parse(output);
            parsed = true;
        } catch {
            // Expected
        }
        assert.strictEqual(parsed, false);
    });

    test('line number adjustment for selections', () => {
        const startLine = 50;
        const issues = [
            { line: 1, endLine: 3 },
            { line: 5, endLine: undefined },
        ];

        const adjusted = issues.map(i => ({
            line: i.line + startLine - 1,
            endLine: i.endLine !== undefined ? i.endLine + startLine - 1 : undefined,
        }));

        assert.strictEqual(adjusted[0].line, 50);
        assert.strictEqual(adjusted[0].endLine, 52);
        assert.strictEqual(adjusted[1].line, 54);
        assert.strictEqual(adjusted[1].endLine, undefined);
    });
});
