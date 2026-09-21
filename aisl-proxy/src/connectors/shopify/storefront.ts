import { AislError } from '../../lib/errors.js';
import { toMinorUnits } from '../../lib/money.js';
import type { Merchant } from '../../db/repositories/merchants.js';
import { requestJson, type HttpOptions } from '../http.js';
import type { CatalogConnector, CatalogSearchRequest, NormalizedProduct } from '../types.js';

/**
 * Product search over the Shopify Storefront GraphQL API.
 *
 * The selection set follows the AISL blueprint (TASK 3) and adds the fields
 * required to normalise into the ACP product shape: availability, canonical
 * URL and image.
 */
const SEARCH_PRODUCTS_QUERY = `
query SearchProducts($query: String!, $first: Int!) {
  products(first: $first, query: $query) {
    edges {
      node {
        id
        title
        description
        handle
        onlineStoreUrl
        availableForSale
        totalInventory
        featuredImage {
          url
        }
        variants(first: 1) {
          edges {
            node {
              id
              availableForSale
              quantityAvailable
              price {
                amount
                currencyCode
              }
            }
          }
        }
      }
    }
  }
}
`;

const VARIANT_QUERY = `
query VariantById($id: ID!) {
  node(id: $id) {
    ... on ProductVariant {
      id
      title
      availableForSale
      quantityAvailable
      price {
        amount
        currencyCode
      }
      image {
        url
      }
      product {
        id
        title
        description
        onlineStoreUrl
      }
    }
  }
}
`;

interface GraphQLResponse<T> {
  data?: T;
  errors?: Array<{ message: string }>;
}

interface ProductNode {
  id: string;
  title: string;
  description: string | null;
  handle: string | null;
  onlineStoreUrl: string | null;
  availableForSale: boolean | null;
  totalInventory: number | null;
  featuredImage: { url: string } | null;
  variants: { edges: Array<{ node: VariantNode }> };
}

interface VariantNode {
  id: string;
  availableForSale?: boolean | null;
  quantityAvailable?: number | null;
  price: { amount: string; currencyCode: string };
}

interface SearchData {
  products: { edges: Array<{ node: ProductNode }> };
}

interface VariantData {
  node:
    | (VariantNode & {
        title: string;
        image: { url: string } | null;
        product: { id: string; title: string; description: string | null; onlineStoreUrl: string | null };
      })
    | null;
}

export class ShopifyStorefrontConnector implements CatalogConnector {
  readonly platform = 'shopify';

  constructor(private readonly http: HttpOptions) {}

  async search(merchant: Merchant, request: CatalogSearchRequest): Promise<NormalizedProduct[]> {
    const credentials = this.credentials(merchant);
    const payload = await requestJson<GraphQLResponse<SearchData>>(
      {
        url: this.endpoint(credentials.store_domain, credentials.storefront_api_version),
        method: 'POST',
        source: 'shopify_storefront',
        headers: { 'X-Shopify-Storefront-Access-Token': credentials.storefront_token },
        body: { query: SEARCH_PRODUCTS_QUERY, variables: { query: request.query, first: request.limit } },
      },
      this.http,
    );

    assertNoGraphQLErrors(payload);
    const edges = payload.data?.products.edges ?? [];

    return edges.flatMap(({ node }) => {
      const variant = node.variants.edges[0]?.node;
      // A product with no purchasable variant cannot be checked out, so it is
      // not something an agent should be shown.
      if (!variant) return [];

      const currency = variant.price.currencyCode.toUpperCase();
      return [
        {
          productId: node.id,
          variantId: variant.id,
          title: node.title,
          description: node.description ?? '',
          priceCents: toMinorUnits(variant.price.amount, currency),
          currency,
          availability: availabilityOf(variant.availableForSale ?? node.availableForSale),
          inventoryQuantity: variant.quantityAvailable ?? node.totalInventory ?? null,
          url: node.onlineStoreUrl ?? this.productUrl(credentials.store_domain, node.handle),
          imageUrl: node.featuredImage?.url ?? null,
        },
      ];
    });
  }

  async getVariant(merchant: Merchant, variantId: string): Promise<NormalizedProduct | null> {
    const credentials = this.credentials(merchant);
    const payload = await requestJson<GraphQLResponse<VariantData>>(
      {
        url: this.endpoint(credentials.store_domain, credentials.storefront_api_version),
        method: 'POST',
        source: 'shopify_storefront',
        headers: { 'X-Shopify-Storefront-Access-Token': credentials.storefront_token },
        body: { query: VARIANT_QUERY, variables: { id: variantId } },
      },
      this.http,
    );

    assertNoGraphQLErrors(payload);
    const node = payload.data?.node;
    if (!node) return null;

    const currency = node.price.currencyCode.toUpperCase();
    return {
      productId: node.product.id,
      variantId: node.id,
      title: node.product.title,
      description: node.product.description ?? '',
      priceCents: toMinorUnits(node.price.amount, currency),
      currency,
      availability: availabilityOf(node.availableForSale),
      inventoryQuantity: node.quantityAvailable ?? null,
      url: node.product.onlineStoreUrl,
      imageUrl: node.image?.url ?? null,
    };
  }

  private endpoint(domain: string, apiVersion: string): string {
    return `https://${domain}/api/${apiVersion}/graphql.json`;
  }

  private productUrl(domain: string, handle: string | null): string | null {
    return handle ? `https://${domain}/products/${handle}` : null;
  }

  private credentials(merchant: Merchant) {
    if (merchant.credentials.platform !== 'shopify') {
      throw AislError.internal(
        'connector_platform_mismatch',
        `shopify storefront connector received a ${merchant.credentials.platform} merchant`,
      );
    }
    return merchant.credentials;
  }
}

function availabilityOf(available: boolean | null | undefined): NormalizedProduct['availability'] {
  if (available === true) return 'in_stock';
  if (available === false) return 'out_of_stock';
  return 'unknown';
}

function assertNoGraphQLErrors<T>(payload: GraphQLResponse<T>): void {
  if (payload.errors && payload.errors.length > 0) {
    throw AislError.upstream(
      'shopify_storefront_graphql_error',
      `Shopify Storefront API returned errors: ${payload.errors.map((error) => error.message).join('; ')}`,
    );
  }
}
