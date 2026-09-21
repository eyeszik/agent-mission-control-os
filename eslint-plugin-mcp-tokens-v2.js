module.exports = {
  rules: {
    'no-hardcoded-colors': {
      meta: {
        type: 'problem',
        docs: { description: 'Disallow hardcoded hex color values.', category: 'Best Practices', recommended: true },
        messages: { hardcodedColor: 'Forbidden hardcoded color value "{{color}}". Use design system tokens.' },
        schema: [],
      },
      create(context) {
        const COLOR_REGEX = /#([a-fA-F0-9]{3,4}|[a-fA-F0-9]{6}|[a-fA-F0-9]{8})\b|(rgba?|hsla?|oklch|color)\([^)]+\)/i;
        return {
          Literal(node) {
            if (typeof node.value === 'string' && COLOR_REGEX.test(node.value)) {
              context.report({ node, messageId: 'hardcodedColor', data: { color: node.value } });
            }
          }
        };
      }
    }
  }
};
